import re
import time
from foundry_local_sdk import FoundryLocalManager
from foundry_local_sdk.configuration import Configuration
from langchain_huggingface import HuggingFaceEmbeddings
# Import retrieve_content() from retriever.py
from retriever import retrieve_content

# Multilingual embedding model — supports Turkish (50+ languages, same 384-dim as MiniLM-L6)
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Safe context limit to prevent RAM overflow during prefill phase
MAX_CONTEXT_CHARS = 2500

# Only use chunks closer than this distance; beyond it the context is too irrelevant
MAX_DISTANCE = 0.90

# If the single best chunk is still farther than this, return "not found" immediately
QUALITY_GATE_DISTANCE = 0.90

# Hard time limit for streaming generation (seconds)
STREAM_TIMEOUT_SECONDS = 180


def _select_and_register_ep(manager):
    available_eps = manager.discover_eps()

    # AMD GPU priority order: DirectML > WebGPU > CUDA
    priority_eps = ['DirectMLExecutionProvider', 'WebGpuExecutionProvider', 'CUDAExecutionProvider']

    selected_ep = None
    is_already_registered = False

    # Find the best available EP based on priority
    for target in priority_eps:
        for ep in available_eps:
            if getattr(ep, 'name', '') == target:
                selected_ep = target
                # Check if its already downloaded
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

    # Hardware Acceleration GPU Setup
    print("(*) Analyzing system hardware for acceleration")
    _select_and_register_ep(manager)
    #----------------------------------------------------------------------------

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
    - Leading page numbers like '35\n' or '2 / 50\n'
    - Excessive blank lines
    - Hyphenated line breaks (e.g. 'ha-\nreket' -> 'hareket')
    """
    # Repair hyphenated line-break splits common in PDF extraction
    text = re.sub(r'-\n\s*', '', text)
    # Remove leading standalone page numbers (e.g. "35\n" at start)
    text = re.sub(r'^\s*\d+\s*\n', '', text)
    # Collapse runs of whitespace/newlines into a single space
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _build_context(retrieved_docs):
    # Filter bad distances, clean each chunk, and cap total to prevent prefill overflow
    chunks = []
    total_chars = 0

    for text, distance in retrieved_docs:
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

    return "\n\n".join(chunks)


def answer_query(user_question, model, embeddings_model):
    print(f"\n[?] Question: {user_question}")

    # 1. Retrieve the top context paragraphs from SQLite
    print("(*) Searching local database for answers")
    retrieved_docs = retrieve_content(user_question, embeddings_model, k=5)

    if not retrieved_docs:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."

    # Log distances for debugging
    for text, dist in retrieved_docs:
        print(f"    dist={dist:.4f} | {text[:60].strip()!r}")

    # Quality gate: if even the best chunk is too far, the topic is not in our DB
    best_distance = retrieved_docs[0][1]
    if best_distance > QUALITY_GATE_DISTANCE:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."

    # Combine retrieved chunks into a single context string (filtering out bad distances)
    context_text = _build_context(retrieved_docs)

    if not context_text:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."

    # 2. Build the System Prompt using the context
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

    # 3. Stream tokens from local LLM — avoids SDK-level operation cancellation
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

        print()  # newline after streamed output
        return None  # already printed inline, caller skips re-printing

    except Exception as e:
        return f"[-] Generation failed: {e}"


if __name__ == "__main__":
    offline_model, embeddings_model = setup_system()
    print("\n" + "="*50)
    print("-- Çevrim Dışı Kriz Asistanı (Offline Crisis Assistant)--")
    print("Çıkmak için 'kapat', 'q', 'cikis', 'exit' yazın.")
    print("="*50)

    try:
        # Infinite CLI Loop
        while True:
            user_input = input("\n[Sen]: ")

            if user_input.lower() in ['kapat', 'q', 'cikis', 'exit']:
                print("(*) Shutting down safely")
                break

            if not user_input.strip():
                continue

            result = answer_query(user_input, offline_model, embeddings_model)

            # answer_query returns None if it already streamed inline, or an error string
            if result is not None:
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print(result)

    finally:
        offline_model.unload()