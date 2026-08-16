"""
generator.py: LLM orchestration for the Offline Crisis Assistant.

Responsibilities:
  - Load/unload the phi-3.5-mini model via Foundry Local
  - Load the embedding model (once at startup)
  - Open a persistent DB connection for the session
  - Pre-embed canonical query cache
  - answer_query(): retrieve (hybrid) -> build context -> stream LLM response
  - Main CLI loop with inventory command routing

Helper logic lives in dedicated modules:
  - query_processor.py  : keyword expansion, Turkish char normalization
  - context_builder.py  : chunk cleaning, deduplication, context assembly
  - state_manager.py    : persistent user inventory / situational profile
  - retriever.py        : hybrid vector + FTS5 BM25 search, RRF fusion
"""

import os
import re
import sys
import time
import numpy as np
from foundry_local_sdk import FoundryLocalManager
from foundry_local_sdk.configuration import Configuration
from langchain_huggingface import HuggingFaceEmbeddings

# Ensure src/ is on the path so sibling packages resolve correctly
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.config import (
    EMBEDDING_MODEL, MAX_CONTEXT_CHARS,
    MAX_DISTANCE, QUALITY_GATE_DISTANCE,
    STREAM_TIMEOUT_SECONDS, MAX_HISTORY_TURNS,
    MAX_GENERATION_TOKENS,
    CACHE_HIT_THRESHOLD, MIN_USEFUL_WORDS, TOP_K
)
from retriever import open_db, retrieve_content
from query_processor import expand_query
from context_builder import build_context
from state_manager import StateManager, clean_llm_response, parse_explicit_inventory_command

# ---------------------------------------------------------------------------
# Module-level caches (persist for the whole process lifetime)
# ---------------------------------------------------------------------------
_embed_cache: dict = {}   # query_string -> np.ndarray

# ---------------------------------------------------------------------------
# Pre-embedded canonical queries for fast query normalisation at runtime.
# Adding a query here costs ~0.05 s at startup; it saves one embed() call
# every time a user asks something semantically close to that query.
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

# Regex used to capture <INVENTORY>...</INVENTORY> blocks in LLM output
_INVENTORY_RE = re.compile(
    r'<INVENTORY>(.*?)</INVENTORY>',
    re.DOTALL | re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_query_cache(embeddings_model) -> dict:
    """
    Pre-embeds all canonical crisis queries at startup.
    Returns {query_string: np.ndarray}.  Cost: ~1 s; saves time for common queries.
    """
    print(f"(*) Pre-computing cache for {len(_COMMON_CRISIS_QUERIES)} canonical queries...")
    cache = {}
    for q in _COMMON_CRISIS_QUERIES:
        cache[q] = np.array(embeddings_model.embed_query(q), dtype=np.float32)
    print("[+] Query cache ready.")
    return cache


def _resolve_query(query: str, embeddings_model, query_cache: dict) -> list:
    """
    Embeds query (with session-level cache) then optionally snaps it to the
    nearest canonical pre-embedded query if within CACHE_HIT_THRESHOLD.
    Returns a plain Python list ready for sqlite_vec serialisation.
    """
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
    """Tries to register the best available GPU execution provider."""
    available_eps = manager.discover_eps()
    priority_eps = [
        'DirectMLExecutionProvider',
        'WebGpuExecutionProvider',
        'CUDAExecutionProvider',
    ]

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


def _strip_inventory_blocks(text: str, state_manager: StateManager) -> str:
    """
    Finds all <INVENTORY>...</INVENTORY> blocks in the LLM output, persists
    each one via StateManager, then removes the blocks from the visible response.
    The user never sees raw JSON; they only see the clean Turkish answer.
    """
    def handle_match(m):
        state_manager.update_from_inventory_block(m.group(1))
        return ""   # remove from visible output

    return _INVENTORY_RE.sub(handle_match, text).strip()


# Keywords that indicate the query is about rationing / supplies / evacuation planning.
# ONLY inject the inventory state block when the query matches one of these.
_INVENTORY_RELEVANT_KEYWORDS = {
    # Explicit inventory/ration terms
    'rasyon', 'rasyonum', 'rasyonlama', 'gunluk rasyon',
    'yiyecek', 'yemek', 'gida', 'atistirmalik',
    'malzeme', 'malzemem', 'malzemeleri', 'malzemelerim',
    'envanter', 'envanterim', 'stok', 'stoklarim',
    # Supply-scoped queries
    'elimde ne', 'elimde var', 'elimde neler',
    'yanimda ne', 'bende ne', 'ne kadar var',
    'kac gun', 'kac gunluk', 'ne kadar surer',
    # Planning / rationing context
    'ne ile idare', 'nasil idare', 'idare eder miyim',
    'tahliye hazirlik', 'hazirlik',
    'ne ile beslenir', 'nasil beslenir',
}


def _is_inventory_relevant(query: str) -> bool:
    """
    Returns True only when the query is explicitly about rationing,
    supplies, or evacuation planning.
    This prevents inventory items from leaking into unrelated answers
    (e.g. Morse code questions getting answered with inventory items).
    """
    from query_processor import normalize_for_matching
    norm = normalize_for_matching(query.lower())
    return any(kw in norm for kw in _INVENTORY_RELEVANT_KEYWORDS)


def _build_system_prompt(context_text: str, state_manager: StateManager,
                         inject_inventory: bool = False,
                         user_question: str = "") -> str:
    """
    Assembles the system prompt. Balanced: 1-sentence intro + step-by-step actions.
    """
    inventory_block = ""
    if inject_inventory:
        state_block = state_manager.get_context_block()
        if state_block:
            inventory_block = f"\nKullanici Envanter Durumu:\n{state_block}\n"

    system_prompt = f"""You are an emergency crisis response AI assistant.
Answer the user's question accurately in clear Turkish using ONLY the Verified Knowledge Sources below.

Instructions:
1. Start with a brief 1-sentence opening explanation, followed by the essential step-by-step instructions from the Sources.
2. Format the steps clearly using bullet points (-) or numbered list (1., 2.).
3. Stay strictly focused on the user's question. Stop immediately once the relevant instructions are provided.
4. Do NOT repeat sections, and do NOT include unrelated procedures, document names, or meta-commentary.
{inventory_block}
Verified Knowledge Sources:
{context_text}"""

    return system_prompt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_system():
    """
    Initialises Foundry Local, loads the LLM and embedding model,
    opens a persistent DB connection, pre-embeds canonical queries,
    and creates a StateManager instance.

    Returns: (model, embeddings_model, db, query_cache, state_manager)
    """
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

    db = open_db()
    query_cache = _build_query_cache(embeddings_model)
    state_manager = StateManager()

    return model, embeddings_model, db, query_cache, state_manager


def answer_query(user_question, model, embeddings_model, db, chat_history,
                 query_cache, state_manager: StateManager):
    """
    Full RAG pipeline:
      0. Contextualise short follow-up questions using chat history
      1. Expand 1-3 word queries with domain keywords
      2. Resolve query to nearest canonical embedding (or fresh embed)
      3. Retrieve top-k chunks from sqlite_vec
      4. Quality gate: abort if best chunk is too distant
      5. Build clean context string
      6. Stream LLM response token by token
      7. Strip <INVENTORY> blocks from output and persist them

    Returns: (response_text: str, was_streamed: bool)
      was_streamed=True  -> tokens already printed; caller must NOT re-print
      was_streamed=False -> caller should print the response (error / not-found)
    """
    print(f"\n[?] Question: {user_question}")

    # 0. Contextualise genuine follow-up questions.
    # Only prepend when the current message STARTS WITH a connector word AND
    # the previous user message was NOT an inventory command.
    # This prevents 'mors alfabesi' being merged with 'envanter ekle su 2 litre'.
    search_query = user_question
    _FOLLOWUP_STARTERS = {
        'peki', 'ya', 'acaba', 'ya da', 'yoksa', 'bunu', 'evet',
        'hayir', 'hayır', 'tamam', 'anladim', 'simdi', 'sonra',
        'o zaman', 'neden', 'nerede',
    }
    first_word = user_question.strip().split()[0].lower() if user_question.strip() else ''
    is_followup = (
        chat_history
        and len(user_question.split()) < 5
        and first_word in _FOLLOWUP_STARTERS
    )
    if is_followup:
        last_user_msg = next(
            (msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"),
            ""
        )
        # Don't contextualize with inventory commands: they would corrupt the query
        if last_user_msg and not last_user_msg.lower().startswith('envanter'):
            search_query = f"{last_user_msg} {user_question}"
            print(f"(*) Contextualized search query: '{search_query}'")

    # 1. Query expansion
    expanded_query = expand_query(search_query)

    # 2. Embedding resolution
    query_vector = _resolve_query(expanded_query, embeddings_model, query_cache)

    # 3. Hybrid retrieval (vector KNN + FTS5 BM25 -> RRF fusion)
    print("(*) Searching local database for answers")
    retrieved_docs = retrieve_content(
        expanded_query, embeddings_model, db, k=TOP_K, query_vector=query_vector
    )

    if not retrieved_docs:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının.", False

    best_distance = retrieved_docs[0][1]
    if best_distance > QUALITY_GATE_DISTANCE:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının.", False

    # 5. Build context
    context_text, citations = build_context(retrieved_docs)

    if not context_text:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının.", False

    cleaned_chunks = context_text.split("\n\n")
    print(f"(*) Cleaned context -> LLM ({len(context_text)} chars, {len(cleaned_chunks)} chunk(s)):")
    for i, ck in enumerate(cleaned_chunks, 1):
        print(f"    [Chunk {i}]: {ck[:120].strip()}")

    # 6. Build prompt: inject inventory ONLY for ration/supply related queries
    inject_inv = _is_inventory_relevant(user_question)
    if inject_inv:
        print("(*) Inventory state injected into prompt (ration/supply query)")
    system_prompt = _build_system_prompt(
        context_text, state_manager,
        inject_inventory=inject_inv,
        user_question=user_question
    )

    print("(*) Generating answer from context")
    chat_client = model.get_chat_client()

    messages = [{"role": "system", "content": system_prompt}]
    if is_followup:
        # Only include user/assistant turns - never re-inject system messages from history
        for msg in chat_history:
            if msg.get("role") in ("user", "assistant") and msg.get("content", "").strip():
                messages.append(msg)
    messages.append({"role": "user", "content": user_question})

    try:
        # Note: Foundry Local ChatClient does not expose max_tokens as a kwarg.
        # We enforce the output length via our programmatic token counter below.
        stream = chat_client.complete_streaming_chat(messages=messages)

        print("\n" + "=" * 50)
        print("Asistan:")
        print("=" * 50)

        raw_tokens = []
        token_count = 0
        start_time = time.time()

        for chunk in stream:
            if time.time() - start_time > STREAM_TIMEOUT_SECONDS:
                print("\n[!] Generation time limit reached.")
                break
            if token_count >= MAX_GENERATION_TOKENS:
                print("\n[!] Token limit reached.")
                break
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                print(delta, end="", flush=True)
                raw_tokens.append(delta)
                token_count += len(delta)

                # Early stop: if model outputted stop tokens, kill stream
                last_chars = ("".join(raw_tokens[-30:]) + delta).lower()
                _STOP_MARKERS = (
                    '[bitti]', '\n---', 'unutmayın', 'unutma',
                    'özetle', 'bu yönergeler', 'her iki teknik', 'not:',
                    'bu bilgileri', 'verilen bilgileri', 'bu yöntemleri', 'bu ilkeleri', 'bu protokol',
                    'bilinç bozukluklarında', 'kizilay_ilk_yardim', '.indd', 'güncelleniyor:',
                    'bu konuda veritabanımda güvenilir bilgi bulunmuyor',
                    'bu konuda veritabanında güvenilir bilgi bulunmuyor'
                )
                if any(m in last_chars for m in _STOP_MARKERS):
                    print("\n[+] Answer completed (stop marker hit).")
                    break

                if _has_repetition_loop(raw_tokens):
                    print("\n[*] Repetition loop detected: terminating stream.")
                    break

        print()
        raw_response = "".join(raw_tokens)

        if not raw_response.strip():
            # Model returned empty output: can happen after [BITTI] cut-off
            return "Bir sorun olustu, lutfen tekrar deneyin.", False

        # Strip [BITTI] marker and artifact annotations before storing in history.
        visible_response = clean_llm_response(raw_response, user_question=user_question)
        # clean_llm_response already strips [BITTI] via regex; also strip any inline occurrence
        visible_response = re.sub(r'\[BITTI\].*', '', visible_response, flags=re.DOTALL).strip()

        if not visible_response:
            return "Bir sorun olustu, lutfen tekrar deneyin.", False

        if citations:
            print("\n--- Kaynaklar ---")
            for c in citations:
                if isinstance(c, dict):
                    stype = (c.get("source_type") or "pdf").upper()
                    sfile = c.get("source") or "dosya"
                    print(f"* [{stype}] {sfile}")
                elif isinstance(c, str):
                    print(f"* {c}")

        return visible_response, True

    except Exception as e:
        return f"[-] Generation failed: {e}", False


def _safe_close_stream(stream):
    """Safely closes a streaming response if the object supports it."""
    if hasattr(stream, 'close'):
        try:
            stream.close()
        except Exception:
            pass


def _has_repetition_loop(raw_tokens: list) -> bool:
    """
    Detects if the LLM has entered a repetition loop or is repeating bullet points / headers.
    """
    if len(raw_tokens) < 10:
        return False

    full_text = "".join(raw_tokens).lower()
    lines = [l.strip("-* 0123456789.:\t").strip() for l in full_text.split('\n') if len(l.strip()) >= 15]

    # If the exact same line/step appears 2+ times in the generated response
    if len(lines) != len(set(lines)):
        return True

    recent_text = " ".join(raw_tokens[-40:]).lower()
    words = [w for w in recent_text.split() if len(w) >= 3]
    if len(words) >= 8:
        for i in range(len(words) - 4):
            trio = f"{words[i]} {words[i+1]} {words[i+2]}"
            if len(trio) >= 10 and recent_text.count(trio) >= 2:
                return True
        last_word = words[-1]
        _STOPWORDS = {'veya', 'gibi', 'bina', 'icin', 'için', 'daha', 'sonra', 'olan', 'durun', 'gidin', 'yapin', 'yapın', 'alın', 'alin'}
        if len(last_word) >= 4 and last_word not in _STOPWORDS and words[-20:].count(last_word) >= 4:
            return True
    return False


def answer_query_generator(
    user_question: str,
    model,
    embeddings_model,
    db,
    chat_history: list = None,
    query_cache: dict = None,
    state_manager: StateManager = None
):
    """
    Generator version of answer_query for Web SSE streaming.
    Yields dictionary payloads:
      {"type": "rag_docs", "docs": [...]}
      {"type": "token", "token": "..."}
      {"type": "done", "full_response": "..."}
    """
    if chat_history is None: chat_history = []
    if query_cache is None: query_cache = {}
    if state_manager is None: state_manager = StateManager()

    print(f"\n[Web Sorgu]: {user_question}")

    # --- PRIORITY 1: Explicit envanter commands (always bypass RAG & LLM) ---
    inv_cmd, inv_data = parse_explicit_inventory_command(user_question)
    if inv_cmd == 'show':
        inv_text = state_manager.get_readable_inventory()
        print(f"(*) Inventory show response generated directly:\n{inv_text}")
        yield {"type": "rag_docs", "docs": []}
        yield {"type": "telemetry", "telemetry": {
            "context_stats": {
                "total_chars": len(inv_text),
                "max_chars": MAX_CONTEXT_CHARS,
                "estimated_tokens": len(inv_text) // 4,
                "inventory_injected": True,
                "inventory_status": "Aktif (Envanter Görüntülendi)",
                "citations": [],
                "system_prompt": f"[ENVANTER DÖKÜMÜ]\n{inv_text}"
            },
            "search_stats": {
                "retrieved_count": 0,
                "best_distance": 0.0,
                "expanded_query": user_question,
                "query": user_question
            }
        }}
        yield {"type": "token", "token": inv_text}
        yield {"type": "done", "full_response": inv_text}
        return
    elif inv_cmd == 'add':
        state_manager.update_inventory_direct(inv_data)
        inv_text = state_manager.get_readable_inventory()
        action_desc = ", ".join(f"{k}: {v}" for k, v in inv_data.items())
        res_msg = f"Envanter güncellendi. Yeni envanteriniz:\n{inv_text}"
        print(f"(*) Inventory add response generated directly:\n{res_msg}")
        yield {"type": "rag_docs", "docs": []}
        yield {"type": "telemetry", "telemetry": {
            "context_stats": {
                "total_chars": len(inv_text),
                "max_chars": MAX_CONTEXT_CHARS,
                "estimated_tokens": len(inv_text) // 4,
                "inventory_injected": True,
                "inventory_status": f"Aktif (Eklendi: {action_desc})",
                "citations": [],
                "system_prompt": f"[ENVANTER GÜNCELLENDİ]\n{inv_text}"
            },
            "search_stats": {
                "retrieved_count": 0,
                "best_distance": 0.0,
                "expanded_query": user_question,
                "query": user_question
            }
        }}
        yield {"type": "token", "token": res_msg}
        yield {"type": "done", "full_response": res_msg}
        return
    elif inv_cmd == 'delete':
        state_manager.remove_inventory_direct(inv_data)
        inv_text = state_manager.get_readable_inventory()
        action_desc = ", ".join(f"{k}: {v}" for k, v in inv_data.items())
        res_msg = f"Envanter güncellendi. Yeni envanteriniz:\n{inv_text}"
        print(f"(*) Inventory delete response generated directly:\n{res_msg}")
        yield {"type": "rag_docs", "docs": []}
        yield {"type": "telemetry", "telemetry": {
            "context_stats": {
                "total_chars": len(inv_text),
                "max_chars": MAX_CONTEXT_CHARS,
                "estimated_tokens": len(inv_text) // 4,
                "inventory_injected": True,
                "inventory_status": f"Aktif (Silindi: {action_desc})",
                "citations": [],
                "system_prompt": f"[ENVANTER GÜNCELLENDİ]\n{inv_text}"
            },
            "search_stats": {
                "retrieved_count": 0,
                "best_distance": 0.0,
                "expanded_query": user_question,
                "query": user_question
            }
        }}
        yield {"type": "token", "token": res_msg}
        yield {"type": "done", "full_response": res_msg}
        return

    # --- PRIORITY 2: Explicit inventory reset command ---
    if user_question.strip().lower() in ('envanter_sifirla', 'envanteri_sifirla', 'envanter sifirla', 'envanteri sifirla'):
        state_manager.clear()
        res_msg = "Envanter sıfırlandı ve tüm kayıtlar silindi."
        print(f"(*) Inventory reset response generated directly.")
        yield {"type": "rag_docs", "docs": []}
        yield {"type": "telemetry", "telemetry": {
            "context_stats": {
                "total_chars": 0,
                "max_chars": MAX_CONTEXT_CHARS,
                "estimated_tokens": 0,
                "inventory_injected": True,
                "inventory_status": "Aktif (Envanter Sıfırlandı)",
                "citations": [],
                "system_prompt": "[ENVANTER SIFIRLANDI]"
            },
            "search_stats": {
                "retrieved_count": 0,
                "best_distance": 0.0,
                "expanded_query": user_question,
                "query": user_question
            }
        }}
        yield {"type": "token", "token": res_msg}
        yield {"type": "done", "full_response": res_msg}
        return

    # --- PRIORITY 3: Free-form inventory statements (no question mark) ---
    has_question = '?' in user_question or any(
        kw in user_question.lower()
        for kw in ('nasil', 'neden', 'nerede', 'kac', 'hangisi', 'mi', 'mu', 'mou')
    )
    if not has_question:
        extracted = state_manager.try_extract_inventory(user_question)
        if extracted:
            state_manager.update_inventory_direct(extracted)
            inv_text = state_manager.get_readable_inventory()
            res_msg = f"Envanterinize eklendi/güncellendi. Güncel envanteriniz:\n{inv_text}"
            print(f"(*) Free-form inventory statement updated directly:\n{res_msg}")
            yield {"type": "rag_docs", "docs": []}
            yield {"type": "telemetry", "telemetry": {
                "context_stats": {
                    "total_chars": len(inv_text),
                    "max_chars": MAX_CONTEXT_CHARS,
                    "estimated_tokens": len(inv_text) // 4,
                    "inventory_injected": True,
                    "inventory_status": "Aktif (Serbest Cümle İle Envanter Güncellendi)",
                    "citations": [],
                    "system_prompt": f"[ENVANTER GÜNCELLENDİ]\n{inv_text}"
                },
                "search_stats": {
                    "retrieved_count": 0,
                    "best_distance": 0.0,
                    "expanded_query": user_question,
                    "query": user_question
                }
            }}
            yield {"type": "token", "token": res_msg}
            yield {"type": "done", "full_response": res_msg}
            return

    # 0. Out-of-domain pre-check for non-crisis queries
    _OUT_OF_DOMAIN_KEYWORDS = {
        'kuantum', 'qubit', 'borsa', 'hisse', 'senedi', 'kripto', 'bitcoin',
        'futbol', 'basketbol', 'süper lig', 'magazin', 'yazılım', 'python'
    }
    q_low = user_question.lower()
    if any(kw in q_low for kw in _OUT_OF_DOMAIN_KEYWORDS):
        msg = "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."
        yield {"type": "rag_docs", "docs": []}
        yield {"type": "token", "token": msg}
        yield {"type": "done", "full_response": msg}
        return

    # 1. Query expansion & resolution
    search_query = user_question
    expanded_query = expand_query(search_query)
    query_vector = _resolve_query(expanded_query, embeddings_model, query_cache)

    # 2. Hybrid retrieval
    print("(*) Searching local database for answers")
    retrieved_docs = retrieve_content(
        expanded_query, embeddings_model, db, k=TOP_K, query_vector=query_vector
    )

    # Yield RAG debug metadata for web UI right sidebar
    doc_payloads = []
    for d in retrieved_docs:
        text = d[0]
        dist = float(d[1])
        source_file = d[2] if len(d) > 2 and d[2] else "rehber.txt"
        page = d[3] if len(d) > 3 else None
        source_type = d[4] if len(d) > 4 else "txt"
        doc_payloads.append({
            "text": text,
            "distance": dist,
            "source_file": source_file,
            "page": page,
            "source_type": source_type,
            "metadata": {"source": source_file, "page": page, "file_name": source_file}
        })
    yield {"type": "rag_docs", "docs": doc_payloads}

    if not retrieved_docs:
        msg = "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."
        yield {"type": "token", "token": msg}
        yield {"type": "done", "full_response": msg}
        return

    best_distance = retrieved_docs[0][1]
    if best_distance > QUALITY_GATE_DISTANCE:
        msg = "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."
        yield {"type": "token", "token": msg}
        yield {"type": "done", "full_response": msg}
        return

    # 3. Build context & prompt
    context_text, citations = build_context(retrieved_docs)
    if not context_text:
        msg = "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."
        yield {"type": "token", "token": msg}
        yield {"type": "done", "full_response": msg}
        return

    inject_inv = _is_inventory_relevant(user_question)
    system_prompt = _build_system_prompt(
        context_text, state_manager,
        inject_inventory=inject_inv,
        user_question=user_question
    )

    yield {"type": "telemetry", "telemetry": {
        "context_stats": {
            "total_chars": len(context_text),
            "max_chars": MAX_CONTEXT_CHARS,
            "estimated_tokens": len(context_text) // 4,
            "inventory_injected": inject_inv,
            "inventory_status": "Aktif (Stok Bilgisi Prompta Eklendi)" if inject_inv else "Pasif (Sorgu stoklama ile ilgili değil)",
            "citations": citations,
            "system_prompt": system_prompt
        },
        "search_stats": {
            "retrieved_count": len(retrieved_docs),
            "best_distance": round(best_distance, 4),
            "expanded_query": expanded_query,
            "query": user_question
        }
    }}

    chat_client = model.get_chat_client()
    messages = [{"role": "system", "content": system_prompt}]
    
    # Include history turns
    if chat_history:
        for msg in chat_history[-MAX_HISTORY_TURNS:]:
            if msg.get("role") in ("user", "assistant") and msg.get("content", "").strip():
                messages.append(msg)
    messages.append({"role": "user", "content": user_question})

    try:
        stream = chat_client.complete_streaming_chat(messages=messages)
        raw_tokens = []
        token_count = 0
        start_time = time.time()

        try:
            for chunk in stream:
                if time.time() - start_time > STREAM_TIMEOUT_SECONDS:
                    break
                if token_count >= MAX_GENERATION_TOKENS:
                    print("\n[!] Token limit reached.")
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    _STOP_MARKERS = (
                        '[bitti]', '\n---', 'unutmayın', 'unutma',
                        'özetle', 'bu yönergeler', 'her iki teknik', 'not:',
                        'bu bilgileri', 'verilen bilgileri', 'bu yöntemleri', 'bu ilkeleri', 'bu protokol',
                        'bilinç bozukluklarında', 'kizilay_ilk_yardim', '.indd', 'güncelleniyor:',
                        'bu konuda veritabanımda güvenilir bilgi bulunmuyor',
                        'bu konuda veritabanında güvenilir bilgi bulunmuyor'
                    )
                    last_chars = ("".join(raw_tokens[-30:]) + delta).lower()
                    if any(m in last_chars for m in _STOP_MARKERS):
                        print("\n[+] Stream stop marker hit: cutting stream early.")
                        break
                    print(delta, end="", flush=True)
                    raw_tokens.append(delta)
                    token_count += len(delta)

                    if _has_repetition_loop(raw_tokens):
                        print("\n[*] Repetition loop detected: terminating stream.")
                        break

                    yield {"type": "token", "token": delta}
        finally:
            _safe_close_stream(stream)

        print()
        if citations:
            print("--- Kaynaklar ---")
            for c in citations:
                if isinstance(c, dict):
                    stype = (c.get("source_type") or "pdf").upper()
                    sfile = c.get("source") or "dosya"
                    print(f"* [{stype}] {sfile}")
                elif isinstance(c, str):
                    print(f"* {c}")

        raw_response = "".join(raw_tokens)
        visible_response = clean_llm_response(raw_response, user_question=user_question)
        visible_response = re.sub(r'\[BITTI\].*', '', visible_response, flags=re.DOTALL).strip()
        yield {"type": "done", "full_response": visible_response}

    except Exception as e:
        err_msg = f"[-] Generation failed: {e}"
        print(err_msg)
        yield {"type": "token", "token": err_msg}
        yield {"type": "done", "full_response": err_msg}



# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    offline_model, embeddings_model, db, query_cache, state_manager = setup_system()

    print("\n" + "="*50)
    print("-- Cevrim Disi Kriz Asistani (Offline Crisis Assistant)--")
    print("Cikmak icin 'kapat', 'q', 'cikis', 'exit' yazin.")
    print("Envanter icin: 'envanter', 'envanter ekle su 5 litre, pil 3', 'envanter sil su'")
    print("Envanter silmek icin: 'envanter_sifirla'")
    print("="*50)

    chat_history = []

    try:
        while True:
            user_input = input("\n[Sen]: ")

            if user_input.lower() in ['kapat', 'q', 'cikis', 'exit']:
                print("(*) Shutting down safely")
                break

            if not user_input.strip():
                continue

            # --- PRIORITY 1: Explicit envanter commands (always bypass RAG) ---
            inv_cmd, inv_data = parse_explicit_inventory_command(user_input)

            if inv_cmd == 'show':
                inv_text = state_manager.get_readable_inventory()
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print(inv_text)
                # Store a NEUTRAL message in history so subsequent RAG queries
                # don't see the full item list and get confused by it.
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({"role": "assistant", "content": "[Envanter gosterildi]"})
                continue

            elif inv_cmd == 'add':
                state_manager.update_inventory_direct(inv_data)
                items_str = ", ".join(f"{k}: {v}" for k, v in inv_data.items())
                msg = f"Kaydedildi: {items_str}"
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print(msg)
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({"role": "assistant", "content": msg})
                continue

            elif inv_cmd == 'delete':
                state_manager.remove_inventory_direct(inv_data)
                
                parts = []
                for k, v in inv_data.items():
                    if str(v).upper() == 'ALL':
                        parts.append(k)
                    else:
                        parts.append(f"{k} ({v} azaldi)")
                        
                msg = f"Silindi/Eksiltildi: {', '.join(parts)}"
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print(msg)
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({"role": "assistant", "content": msg})
                continue

            # --- PRIORITY 2: envanter_sifirla ---
            if user_input.lower() == 'envanter_sifirla':
                state_manager.clear()
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print("Envanter ve profil bilgisi silindi.")
                continue

            # --- PRIORITY 3: Best-effort free-form extraction (no question) ---
            extracted = state_manager.try_extract_inventory(user_input)
            if extracted:
                state_manager.update_inventory_direct(extracted)
                items_str = ", ".join(f"{k}: {v}" for k, v in extracted.items())
                print(f"[+] Otomatik kaydedildi -> {items_str}")
                has_question = '?' in user_input or any(
                    w in user_input.lower() for w in
                    ['nasil', 'nasil', 'ne kadar', 'ne yapmal', 'kac gun', 'kac gun',
                     'ne zaman', 'neden', 'nereye', 'ne yapay', 'ne yapal']
                )
                if not has_question:
                    msg = f"Tamam, kaydettim: {items_str}. Baska bir konuda yardim edebilir miyim?"
                    print("\n" + "="*50)
                    print("Asistan:")
                    print("="*50)
                    print(msg)
                    chat_history.append({"role": "user", "content": user_input})
                    chat_history.append({"role": "assistant", "content": msg})
                    if len(chat_history) > MAX_HISTORY_TURNS * 2:
                        chat_history = chat_history[-(MAX_HISTORY_TURNS * 2):]
                    continue
                # Has a question -> fall through to RAG with updated inventory context

            result, was_streamed = answer_query(
                user_input, offline_model, embeddings_model, db,
                chat_history, query_cache, state_manager
            )

            if result and not was_streamed:
                print("\n" + "="*50)
                print("Asistan:")
                print("="*50)
                print(result)

            if was_streamed and result:
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({"role": "assistant", "content": result})
                if len(chat_history) > MAX_HISTORY_TURNS * 2:
                    chat_history = chat_history[-(MAX_HISTORY_TURNS * 2):]

    finally:
        db.close()
        offline_model.unload()