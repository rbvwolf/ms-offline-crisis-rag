import os
import re
import sys
import time
import numpy as np
from foundry_local_sdk import FoundryLocalManager
from foundry_local_sdk.configuration import Configuration
from langchain_huggingface import HuggingFaceEmbeddings

# Add src/ to path so we can import from core.config
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import (
    EMBEDDING_MODEL, MAX_CONTEXT_CHARS,
    MAX_DISTANCE, QUALITY_GATE_DISTANCE,
    STREAM_TIMEOUT_SECONDS, MAX_HISTORY_TURNS,
    CACHE_HIT_THRESHOLD
)
from retriever import open_db, retrieve_content


# ---------------------------------------------------------------------------
# Query expansion: if user types 1-2 words, append relevant keywords
# to help the embedding model find better matches in the knowledge base.
# ---------------------------------------------------------------------------
_QUERY_EXPANSIONS = {
    "deprem":       "deprem anında güvenli davranış sarsıntı enkaz",
    "yangın":       "yangın söndürme kaçış tahliye duman",
    "su":           "su arıtma temizleme içilebilir hale getirme",
    "ilk yardım":   "ilk yardım acil müdahale yaralı",
    "mors":         "mors alfabesi kısa uzun sinyal iletişim",
    "kırık":        "kırık kol bacak atel sabitleme müdahale",
    "yanık":        "yanık deri soğutma sarma müdahale",
    "kanama":       "kanama yara baskı uygulama durdurma",
    "enkaz":        "enkaz altında nefes bekleme kurtarma sinyal",
    "rasyon":       "rasyon yiyecek su günlük plan hesaplama",
    "barınak":      "barınak sığınak çadır kurma afet",
    "telsiz":       "telsiz haberleşme frekans PMR acil iletişim",
    "psikoloji":    "psikolojik destek sakinleştirme panik stres",
    "çocuk":        "çocuk sakinleştirme panik korku psikolojik",
}

# ---------------------------------------------------------------------------
# Pre-embedded canonical queries used to "snap" similar user queries to a
# known, well-formed version — improves retrieval consistency.
# ---------------------------------------------------------------------------
_COMMON_CRISIS_QUERIES = [
    "deprem anında ne yapmalıyım güvenli davranış",
    "su nasıl arıtılır içilebilir hale getirilir",
    "kırık kola nasıl ilk yardım yapılır atel",
    "mors alfabesi nasıl kullanılır sinyal verme",
    "yangın çıkarsa ne yapmalı kaçış tahliye",
    "yara kanamayı nasıl durdururum baskı",
    "enkaz altında kaldım ne yapayım hayatta kalma",
    "bebek çocuk panikliyor sakinleştirme psikoloji",
    "afette yiyecek su rasyon günlük plan",
    "deprem sonrası gaz kaçağı elektrik tehlikesi",
    "mors işaretleri sinyal sos acil",
    "boğulma ilk yardım kurtarma",
]


def _expand_short_query(query):
    """
    If the query is 1-2 words and matches a known keyword,
    appends relevant terms to improve retrieval quality.
    """
    q = query.strip().lower()
    if len(q.split()) > 3:
        return query  # long enough, no expansion needed

    for keyword, expansion in _QUERY_EXPANSIONS.items():
        if keyword in q:
            expanded = f"{query} {expansion}"
            print(f"(*) Short query expanded: '{query}' -> '{expanded[:60]}...'")
            return expanded

    return query


def _build_query_cache(embeddings_model):
    """
    Pre-embeds all canonical crisis queries at startup.
    Returns a dict {query_string: np.array(embedding)}.
    The small startup cost (~1s) saves embedding time on repeated common queries.
    """
    print(f"(*) Pre-computing cache for {len(_COMMON_CRISIS_QUERIES)} canonical queries...")
    cache = {}
    for q in _COMMON_CRISIS_QUERIES:
        cache[q] = np.array(embeddings_model.embed_query(q), dtype=np.float32)
    print("[+] Query cache ready.")
    return cache


def _resolve_query(query, embeddings_model, query_cache):
    """
    Embeds the query. If a canonical pre-embedded query is within
    CACHE_HIT_THRESHOLD, returns that canonical embedding instead.
    This normalizes near-identical queries to a consistent vector.
    Always returns a plain Python list suitable for sqlite_vec.
    """
    user_vec = np.array(embeddings_model.embed_query(query), dtype=np.float32)

    if not query_cache:
        return user_vec.tolist()

    best_dist = float('inf')
    best_canonical = None
    best_vec = None

    for canonical, cached_vec in query_cache.items():
        dist = float(np.linalg.norm(user_vec - cached_vec))
        if dist < best_dist:
            best_dist = dist
            best_canonical = canonical
            best_vec = cached_vec

    if best_dist < CACHE_HIT_THRESHOLD:
        print(f"(*) Cache hit: '{best_canonical[:50]}' (dist={best_dist:.3f})")
        return best_vec.tolist()

    return user_vec.tolist()


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

    # Open a single persistent DB connection for the entire session
    db = open_db()

    # Pre-embed canonical queries for fast normalization at query time
    query_cache = _build_query_cache(embeddings_model)

    return model, embeddings_model, db, query_cache


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
            if len(name) > 45:
                name = name[:45] + "..."
            label = f"{name} (s.{page_number + 1})" if page_number >= 0 else name
            if label not in citations:
                citations.append(label)

    return "\n\n".join(chunks), citations


def answer_query(user_question, model, embeddings_model, db, chat_history, query_cache):
    """
    Expands short queries, resolves via cache, retrieves context, and streams
    the LLM response token by token.

    Returns: (response_text: str, was_streamed: bool)
      - was_streamed=True  → tokens already printed inline; caller must not re-print
      - was_streamed=False → caller should print the response (error / not-found)
    """
    print(f"\n[?] Question: {user_question}")

    # 1. Expand short queries (1-2 words) before retrieval
    expanded_query = _expand_short_query(user_question)

    # 2. Resolve to canonical embedding if very close to a pre-cached query
    query_vector = _resolve_query(expanded_query, embeddings_model, query_cache)

    # 3. Retrieve — pass pre-computed vector to skip redundant embedding
    print("(*) Searching local database for answers")
    retrieved_docs = retrieve_content(
        expanded_query, embeddings_model, db, k=3, query_vector=query_vector
    )

    if not retrieved_docs:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının.", False

    # 4. Show RAW results (truncated) for debugging
    print("(*) Raw retrieval results:")
    for row in retrieved_docs:
        text, dist = row[0], row[1]
        print(f"    dist={dist:.4f} | {text[:60].strip()!r}")

    best_distance = retrieved_docs[0][1]
    if best_distance > QUALITY_GATE_DISTANCE:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının.", False

    context_text, citations = _build_context(retrieved_docs)

    if not context_text:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının.", False

    # 5. Show CLEANED context so we can verify what actually goes to the LLM
    cleaned_chunks = context_text.split("\n\n")
    print(f"(*) Cleaned context → LLM ({len(context_text)} chars, {len(cleaned_chunks)} chunk(s)):")
    for i, ck in enumerate(cleaned_chunks, 1):
        print(f"    [Chunk {i}]: {ck[:120].strip()}")

    # Shortened system prompt — phi-3.5-mini follows concise instructions more reliably
    system_prompt = f"""Sen 'Offline Kriz Asistanı'sın. Görevin internetsiz, afet ortamında hayat kurtarmak.

KURALLAR:
1. SADECE aşağıdaki <CONTEXT> içindeki bilgileri kullan. Yoksa: "Veritabanımda bu bilgi bulunmuyor." de.
2. Türkçe yaz. (Soru İngilizce ise İngilizce cevap ver.)
3. Kısa yaz: madde listesi, uzun paragraf yok.
4. Uyarı, not veya açıklama ekleme. Sadece gerçeği ver.
5. Önceki konuşmayı takip et; "peki ya", "bunlar" gibi devam sorularında bağlamı kullan.

MODLAR:
- Panik/Çocuk: Sakin, teskin edici ton. Psikolojik destek öncelikli.
- Tıbbi acil: İlk adımı ver, ardından Evet/Hayır sorusu sor (örn: "Bilinç açık mı?").
- Rasyon: Verilen miktar ve kişi sayısıyla günlük plan yap.

<CONTEXT>
{context_text}
</CONTEXT>"""

    print("(*) Generating answer from context")
    chat_client = model.get_chat_client()

    # Build multi-turn message list: system → history → current question
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)
    messages.append({"role": "user", "content": user_question})

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

        return "".join(full_response), True

    except Exception as e:
        return f"[-] Generation failed: {e}", False


if __name__ == "__main__":
    offline_model, embeddings_model, db, query_cache = setup_system()
    print("\n" + "="*50)
    print("-- Çevrim Dışı Kriz Asistanı (Offline Crisis Assistant)--")
    print("Çıkmak için 'kapat', 'q', 'cikis', 'exit' yazın.")
    print("="*50)

    # Stores last MAX_HISTORY_TURNS turns as {"role": ..., "content": ...} dicts
    chat_history = []

    try:
        while True:
            user_input = input("\n[Sen]: ")

            if user_input.lower() in ['kapat', 'q', 'cikis', 'exit']:
                print("(*) Shutting down safely")
                break

            if not user_input.strip():
                continue

            result, was_streamed = answer_query(
                user_input, offline_model, embeddings_model, db, chat_history, query_cache
            )

            # If not streamed inline, print now (error or not-found message)
            if result and not was_streamed:
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print(result)

            # Only successful LLM answers go into conversation history
            if was_streamed and result:
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({"role": "assistant", "content": result})
                # Keep only the last MAX_HISTORY_TURNS turns (2 messages per turn)
                if len(chat_history) > MAX_HISTORY_TURNS * 2:
                    chat_history = chat_history[-(MAX_HISTORY_TURNS * 2):]

    finally:
        db.close()
        offline_model.unload()