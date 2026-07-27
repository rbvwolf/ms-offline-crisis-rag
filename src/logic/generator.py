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
    CACHE_HIT_THRESHOLD, MIN_USEFUL_WORDS
)
from retriever import open_db, retrieve_content

# Module-level embedding cache: avoids re-embedding identical query strings
_embed_cache: dict = {}


# ---------------------------------------------------------------------------
# Query expansion: if user types 1-2 words, append relevant keywords
# to help the embedding model find better matches in the knowledge base.
# ---------------------------------------------------------------------------
# Keys use ASCII so matching works whether the user types with Turkish keyboard or not.
# Values stay as full Turkish to give the embedding model better semantic signals.
_QUERY_EXPANSIONS = {
    "deprem":       "deprem aninda guvensiz sarsinti enkaz",
    "yangin":       "yangin sondurme kacis tahliye duman",
    "su":           "su aritma temizleme icilebilir hale getirme",
    "ilk yardim":   "ilk yardim acil mudahale yarali",
    "mors":         "mors alfabesi kisa uzun sinyal iletisim",
    "kirik":        "kirik kol bacak atel sabitleme mudahale",
    "yanik":        "yanik deri sogutma sarma mudahale",
    "kanama":       "kanama yara baski uygulama durdurma",
    "enkaz":        "enkaz altinda nefes bekleme kurtarma sinyal",
    "rasyon":       "rasyon yiyecek su gunluk plan hesaplama",
    "barinak":      "barinak siginak cadur kurma afet",
    "telsiz":       "telsiz haberlesme frekans PMR acil iletisim",
    "psikoloji":    "psikolojik destek sakinlestirme panik stres",
    "cocuk":        "cocuk sakinlestirme panik korku psikolojik",
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


def _normalize_for_matching(s):
    """
    Converts Turkish-specific characters to ASCII equivalents.
    Used only for keyword matching — NOT for embedding (embedding needs real chars).
    """
    return (
        s.replace('\u0131', 'i').replace('\u0130', 'i')   # ı İ
         .replace('\u011f', 'g').replace('\u011e', 'g')   # ğ Ğ
         .replace('\u00fc', 'u').replace('\u00dc', 'u')   # ü Ü
         .replace('\u015f', 's').replace('\u015e', 's')   # ş Ş
         .replace('\u00f6', 'o').replace('\u00d6', 'o')   # ö Ö
         .replace('\u00e7', 'c').replace('\u00c7', 'c')   # ç Ç
    )


def _expand_short_query(query):
    """
    If the query is 1-3 words and matches a known keyword (ASCII-normalized),
    appends relevant terms to improve retrieval quality.
    """
    q = query.strip().lower()
    if len(q.split()) > 3:
        return query  # long enough, no expansion needed

    q_norm = _normalize_for_matching(q)

    for keyword, expansion in _QUERY_EXPANSIONS.items():
        # keyword is already ASCII; q_norm is normalized — safe substring check
        if keyword in q_norm:
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
    Embeds the query (with in-session cache) and optionally snaps it to a
    pre-embedded canonical query if very close (CACHE_HIT_THRESHOLD).
    Always returns a plain Python list suitable for sqlite_vec.
    """
    # Embedding cache: skip re-embedding if this exact string was already processed
    if query in _embed_cache:
        print("(*) Embedding cache hit")
        user_vec = _embed_cache[query]
    else:
        user_vec = np.array(embeddings_model.embed_query(query), dtype=np.float32)
        _embed_cache[query] = user_vec

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
    - Weird PDF bullet points like 'Ø'
    """
    text = re.sub(r'-\n\s*', '', text)
    text = re.sub(r'^\s*\d+\s*\n', '', text)
    # Replace weird PDF bullet points with standard dash
    text = text.replace('Ø', '-')
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _build_context(retrieved_docs):
    """
    Filters chunks by distance, deduplicates, removes short chunks,
    cleans text, caps total chars, and collects unique citation labels.
    Returns (context_string, [citations]).
    """
    chunks = []
    citations = []
    seen_fingerprints = set()  # deduplication: first 80 cleaned chars as key
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

        # Skip very short chunks — likely headers, page numbers, or table fragments
        if len(cleaned.split()) < MIN_USEFUL_WORDS:
            continue

        # Deduplication: skip if this chunk is nearly identical to an earlier one
        fingerprint = cleaned[:80].lower()
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)

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

    # 0. Contextualize follow-up questions
    # If the user asks a short follow-up, prepend the last question for better retrieval
    search_query = user_question
    if chat_history and len(user_question.split()) < 6:
        last_user_msg = next((msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"), "")
        if last_user_msg:
            search_query = f"{last_user_msg} {user_question}"
            print(f"(*) Contextualized search query: '{search_query}'")

    # 1. Expand short queries (1-3 words) before retrieval
    expanded_query = _expand_short_query(search_query)

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
    print(f"(*) Cleaned context -> LLM ({len(context_text)} chars, {len(cleaned_chunks)} chunk(s)):")
    for i, ck in enumerate(cleaned_chunks, 1):
        print(f"    [Chunk {i}]: {ck[:120].strip()}")

    system_prompt = f"""Sen 'Offline Kriz Asistanı'sın. Görevin internetsiz, afet ortamında hayat kurtarmak.

KURALLAR:
1. SADECE asagidaki <CONTEXT> icindeki bilgileri kullan. Yoksa: "Veritabanımda bu bilgi bulunmuyor." de.
2. Turkce yaz. (Soru Ingilizce ise Ingilizce cevap ver.)
3. Kisa yaz: madde listesi, uzun paragraf yok.
4. Uyari, not, aciklama, takip sorusu veya ek yorum ekleme. Cevabın sonuna hicbir sey ekleme. "[Pesi]:", "Not:", "Sonraki adim:" gibi ekler yasak.
5. Onceki konusmayi takip et; devam sorularinda baglami kullan.

MODLAR:
- Panik/Cocuk: Sakin, teskin edici ton. Psikolojik destek oncelikli.
- Tibbi acil: Ilk adimi ver, ardindan Evet/Hayir sorusu sor (orn: "Bilinc acik mi?").
- Rasyon: Verilen miktar ve kisi sayisiyla gunluk plan yap.

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