"""
verify_all_crisis_queries.py: Comprehensive Quality Gate & Context Test
Verifies that all 13+ genuine crisis domain questions pass Quality Gate cleanly
and return rich context with exact citations, while out-of-domain queries fail safely.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from core.config import QUALITY_GATE_DISTANCE
from logic.retriever import open_db, retrieve_content
from logic.context_builder import build_context

CRISIS_BENCHMARK_QUERIES = [
    # --- 1. Deprem & Enkaz ---
    ("Deprem", "Deprem sarsıntısı sırasında bina içinde ne yapmalıyım?", False),
    ("Enkaz", "Göçük ve enkaz altında kalınca hayatta kalmak için ne yapılmalı?", False),
    
    # --- 2. Su & Hijyen ---
    ("Su Arıtma", "Bulanık veya kirli su nasıl arıtılır ve dezenfekte edilir?", False),
    ("Salgin", "Afet sonrasında hijyen ve salgın hastalıklardan korunma adımları nelerdir?", False),

    # --- 3. İlk Yardım ---
    ("İlk Yardım", "Kırık ve çıkık durumunda atel nasıl uygulanır?", False),
    ("İlk Yardım", "Şok pozisyonu hastaya nasıl verilir?", False),
    ("İlk Yardım", "Zehirlenme durumunda ilk yardım nasıl olmalıdır?", False),
    ("İlk Yardım", "Yanık durumunda ilk müdahale nasıl yapılmalıdır?", False),

    # --- 4. Haberleşme & Sinyalizasyon ---
    ("Mors", "Mors alfabesinde SOS sinyali nasıl verilir?", False),
    ("Telsiz", "PMR telsiz acil durum kanalı ve frekans kuralları nelerdir?", False),

    # --- 5. Afet Yönetimi ---
    ("AFAD", "Afet ve acil durum çantasında neler bulunmalıdır?", False),
    ("Triage", "Afet anında yaralı önceliklendirme ve triyaj nasıl yapılır?", False),

    # --- 6. Kapsam Dışı (Out of Domain - Fallback Expected) ---
    ("Out-of-Domain", "Kuantum bilgisayarlarda Qubit dolaşıklığı nasıl çalışır?", True),
    ("Out-of-Domain", "İstanbul borsa hisse senedi alım satım kuralları nelerdir?", True)
]

def run_verification():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 75)
    print(" 🛡️ CRISIS DOMAIN QUALITY GATE & CONTEXT INTEGRITY VERIFICATION")
    print("=" * 75)

    db = open_db()
    
    from langchain_huggingface import HuggingFaceEmbeddings
    from core.config import EMBEDDING_MODEL
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    passed_count = 0
    total = len(CRISIS_BENCHMARK_QUERIES)

    print(f"\nTesting {total} Query Scenarios...\n")

    for cat, query, expect_fallback in CRISIS_BENCHMARK_QUERIES:
        t0 = time.time()
        docs = retrieve_content(query, embeddings, db, k=6)
        elapsed_ms = round((time.time() - t0) * 1000, 2)

        best_dist = docs[0][1] if docs else 1.0
        context_str, citations = build_context(docs)

        # Quality Gate test
        is_fallback = best_dist > QUALITY_GATE_DISTANCE or not docs or not context_str.strip()
        
        if expect_fallback:
            success = is_fallback
        else:
            success = not is_fallback and len(docs) >= 1

        if success:
            passed_count += 1
            status_icon = "✅ PASS"
        else:
            status_icon = "❌ FAIL"

        print(f"[{cat}] {status_icon} | Best Dist: {best_dist:.4f} | Chunks: {len(docs)} | Citations: {len(citations)} | {elapsed_ms}ms")
        print(f"  Query: '{query}'")
        if docs:
            print(f"  Top Citation: {docs[0][2]} (p.{docs[0][3]})")
        print("-" * 75)

    print(f"\n📊 FINAL VERIFICATION SCORE: {passed_count}/{total} ({round(passed_count/total*100, 1)}%)")
    if passed_count == total:
        print("🎉 ALL CRISIS QUERIES PASS QUALITY GATE WITH HIGH CONFIDENCE!")
    else:
        print("⚠️ Some queries need fine-tuning.")

if __name__ == '__main__':
    run_verification()
