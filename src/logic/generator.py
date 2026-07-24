import os
import re
import sys
import time
from foundry_local_sdk import FoundryLocalManager
from foundry_local_sdk.configuration import Configuration
from langchain_huggingface import HuggingFaceEmbeddings

# Add src/ to path so we can import from core.config
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import (
    EMBEDDING_MODEL, MAX_CONTEXT_CHARS,
    MAX_DISTANCE, QUALITY_GATE_DISTANCE, STREAM_TIMEOUT_SECONDS
)
from retriever import retrieve_content


def _select_and_register_ep(manager):
    available_eps = manager.discover_eps()

    # AMD GPU priority order: DirectML > WebGPU > CUDA
    priority_eps = ['DirectMLExecutionProvider', 'WebGpuExecutionProvider', 'CUDAExecutionProvider']

    selected_ep = None
    is_already_registered = False

    for target in priority_eps:
        for ep in available_eps:
            if getattr(ep, 'name', '') == target:
                selected_ep = target
                is_already_registered = getattr(ep, 'is_registered', False)
                break
        if selected_ep:
            break

    if not selected_ep:
        print("(*) No dedicated GPU provider found. Defaulting to CPU/RAM processing")
        return None

    print(f"(*) Compatible GPU provider found: {selected_ep}")

    if is_already_registered:
        print(f"[+] {selected_ep} is already registered. Skipping download.")
    else:
        print(f"(*) Downloading and registering {selected_ep}")
        try:
            manager.download_and_register_eps(names=[selected_ep])
            print(f"[+] Successfully registered {selected_ep}! Offloading tasks to GPU")
        except Exception as e:
            print(f"[-] Failed to register GPU provider. Falling back to CPU. Error: {e}")
            return None

    return selected_ep


def setup_system():
    print("(*) Starting foundry local client")
    FoundryLocalManager.initialize(Configuration(app_name="OfflineCrisisRAG"))
    manager = FoundryLocalManager.instance

    print("(*) Analyzing system hardware for acceleration")
    _select_and_register_ep(manager)

    model_name = "phi-3.5-mini"
    print(f"(*) Loading offline model: {model_name}")
    model = manager.catalog.get_model(model_name)
    try:
        model.load()
    except Exception:
        model.download()
        model.load()

    print("(*) Loading embedding model ONCE (Strictly Offline)...")
    embeddings_model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'local_files_only': True},
        encode_kwargs={'normalize_embeddings': True}
    )

    return model, embeddings_model


def _clean_chunk_text(text):
    """
    Strips PDF artifacts from a chunk before it is sent to the LLM:
    - Leading page numbers like '35\\n' or '2 / 50\\n'
    - Excessive blank lines
    - Hyphenated line breaks (e.g. 'ha-\\nreket' -> 'hareket')
    """
    text = re.sub(r'-\n\s*', '', text)
    text = re.sub(r'^\s*\d+\s*\n', '', text)
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _build_context(retrieved_docs):
    """
    Filters chunks by distance, cleans text, caps total chars, and
    collects unique citation labels. Returns (context_string, [citations]).
    """
    chunks = []
    citations = []
    total_chars = 0

    for row in retrieved_docs:
        text, distance = row[0], row[1]
        source_file = row[2] if len(row) > 2 else None
        page_number = row[3] if len(row) > 3 else -1

        if distance > MAX_DISTANCE:
            continue

        cleaned = _clean_chunk_text(text)
        if not cleaned:
            continue

        if total_chars + len(cleaned) > MAX_CONTEXT_CHARS:
            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining > 100:
                chunks.append(cleaned[:remaining])
            break

        chunks.append(cleaned)
        total_chars += len(cleaned)

        # Build citation label for this chunk
        if source_file:
            name = os.path.splitext(source_file)[0]
            # Truncate long auto-generated filenames
            if len(name) > 45:
                name = name[:45] + "..."
            label = f"{name} (s.{page_number + 1})" if page_number >= 0 else name
            if label not in citations:
                citations.append(label)

    return "\n\n".join(chunks), citations


def answer_query(user_question, model, embeddings_model):
    print(f"\n[?] Question: {user_question}")

    print("(*) Searching local database for answers")
    retrieved_docs = retrieve_content(user_question, embeddings_model, k=5)

    if not retrieved_docs:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."

    for row in retrieved_docs:
        text, dist = row[0], row[1]
        print(f"    dist={dist:.4f} | {text[:60].strip()!r}")

    best_distance = retrieved_docs[0][1]
    if best_distance > QUALITY_GATE_DISTANCE:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."

    context_text, citations = _build_context(retrieved_docs)

    if not context_text:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."

    system_prompt = f"""You are the 'Offline Crisis Assistant', an AI designed to operate directly on a user's device during extreme emergencies where the internet is down. Your sole purpose is to save lives, provide calm psychological support, and manage resources safely.

    CRITICAL DIRECTIVES:
    1. STRICT GROUNDING (RAG): You must answer the user's query using ONLY the information provided in the <CONTEXT> block below. If the answer is not present in the context, you MUST state: "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının." Do NOT hallucinate or invent information under any circumstances.
    2. OUTPUT LANGUAGE: Use Turkish as default, if the user give input fully %100 English, use English. First language is TURKISH.
    3. CLI OPTIMIZATION: Your output will be displayed on a black terminal screen to save battery. Use extremely short, concise sentences. Use bullet points. Avoid long paragraphs.
    4. NO DISCLAIMERS: NEVER add explanations. NEVER add notes or disclaimers. Do NOT say "Not:" or "Note:". Just provide the raw facts.

    SPECIAL MODES & TRIGGERS:
    - PANIC & CHILD MODE: If the user input expresses fear, panic, or mentions crying children, instantly adopt a highly empathetic, calming, and soothing tone. Prioritize psychological first aid or fairy tales found in the <CONTEXT>.
    - TRIAGE MODE: For urgent medical situations, DO NOT provide a massive wall of text. Provide immediate first steps and ask a direct Yes/No question to guide the user (e.g., "Hastanın bilinci açık mı? (Evet/Hayır)").
    - RATION CALCULATION: If the user inputs numbers regarding food or water supplies, acknowledge the inventory and provide a strictly logical, daily rationing plan based on survival guidelines in the <CONTEXT>.

    <CONTEXT>
    {context_text}
    </CONTEXT>

    Remember: Keep it short, factual, in Turkish, and strictly bound to the context."""

    print("(*) Generating answer from context")
    chat_client = model.get_chat_client()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_question}
    ]

    try:
        stream = chat_client.complete_streaming_chat(messages=messages)

        print("\n" + "=" * 50)
        print("Asistan:")
        print("=" * 50)

        full_response = []
        start_time = time.time()

        for chunk in stream:
            if time.time() - start_time > STREAM_TIMEOUT_SECONDS:
                print("\n[!] Generation limit reached.")
                break
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                print(delta, end="", flush=True)
                full_response.append(delta)

        print()

        # Print source citations after the answer (programmatic, not hallucinated)
        if citations:
            print("\n--- Kaynaklar ---")
            for c in citations:
                print(f"  • {c}")

        return None  # already printed inline

    except Exception as e:
        return f"[-] Generation failed: {e}"


if __name__ == "__main__":
    offline_model, embeddings_model = setup_system()
    print("\n" + "="*50)
    print("-- Çevrim Dışı Kriz Asistanı (Offline Crisis Assistant)--")
    print("Çıkmak için 'kapat', 'q', 'cikis', 'exit' yazın.")
    print("="*50)

    try:
        while True:
            user_input = input("\n[Sen]: ")

            if user_input.lower() in ['kapat', 'q', 'cikis', 'exit']:
                print("(*) Shutting down safely")
                break

            if not user_input.strip():
                continue

            result = answer_query(user_input, offline_model, embeddings_model)

            if result is not None:
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print(result)

    finally:
        offline_model.unload()