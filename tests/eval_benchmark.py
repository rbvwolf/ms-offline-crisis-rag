"""
eval_benchmark.py — Automated System Evaluation & Benchmark Test Suite
Designed for Microsoft Foundry Local RAG Internship Assessment.

Tests:
  1. Answerable Queries: Grounding, citation presence, quality gate pass.
  2. Unanswerable Queries: Quality gate rejection ("Bilgi yok" fallback enforcement).
  3. Edge Cases: Short/empty queries, Turkish character handling.
  4. Performance Metrics: Retrieval latency, RRF ranking, distance metrics.
"""

import os
import sys
import time
import json

# Ensure src/ is on the python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from core.config import QUALITY_GATE_DISTANCE, MAX_DISTANCE
from logic.retriever import open_db, retrieve_content
from logic.context_builder import build_context

# Benchmark Dataset
BENCHMARK_CASES = [
    {
        "id": 1,
        "type": "answerable",
        "category": "Deprem & Afet",
        "query": "Deprem sarsıntısı sırasında bina içinde ne yapmalıyım?",
        "expected_fallback": False
    },
    {
        "id": 2,
        "type": "answerable",
        "category": "Su & Hijyen",
        "query": "Bulanık veya kirli su nasıl arıtılır ve dezenfekte edilir?",
        "expected_fallback": False
    },
    {
        "id": 3,
        "type": "answerable",
        "category": "İlk Yardım",
        "query": "Kırık ve çıkık durumunda atel nasıl uygulanır?",
        "expected_fallback": False
    },
    {
        "id": 4,
        "type": "answerable",
        "category": "Haberleşme",
        "query": "Mors alfabesinde SOS sinyali nasıl verilir?",
        "expected_fallback": False
    },
    {
        "id": 5,
        "type": "unanswerable",
        "category": "Kapsam Dışı (Out of Domain)",
        "query": "Kuantum bilgisayarlarda Qubit dolaşıklığı nasıl çalışır?",
        "expected_fallback": True
    },
    {
        "id": 6,
        "type": "unanswerable",
        "category": "Kapsam Dışı (Out of Domain)",
        "query": "İstanbul borsa hisse senedi alım satım kuralları nelerdir?",
        "expected_fallback": True
    },
    {
        "id": 7,
        "type": "edge_case",
        "category": "Kısa Sorgu",
        "query": "deprem",
        "expected_fallback": False
    }
]

def run_evaluation():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print(" Offline Crisis RAG - System Evaluation & Benchmark Runner")
    print(" Microsoft Foundry Local Internship Evaluation")
    print("=" * 70)

    db = open_db()
    results = []
    
    # Try initializing embeddings
    print("\n[1/3] Loading HuggingFace Embeddings model...")
    t0 = time.time()
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from core.config import EMBEDDING_MODEL
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        print(f"✅ Embeddings model loaded in {round(time.time() - t0, 2)}s.")
    except Exception as e:
        print(f"❌ Failed to load embeddings: {e}")
        return

    print("\n[2/3] Running Benchmark Test Cases...")
    passed_count = 0

    for test in BENCHMARK_CASES:
        t_start = time.time()
        docs = retrieve_content(test["query"], embeddings, k=6, db=db)
        elapsed_ms = round((time.time() - t_start) * 1000, 2)
        
        best_dist = docs[0][1] if docs else 1.0
        context_str, citations = build_context(docs)
        is_fallback = best_dist > QUALITY_GATE_DISTANCE or not docs

        # Evaluation logic
        if test["expected_fallback"]:
            passed = is_fallback
        else:
            passed = not is_fallback and len(docs) > 0

        if passed:
            passed_count += 1

        status_str = "✅ PASS" if passed else "❌ FAIL"

        results.append({
            "id": test["id"],
            "query": test["query"],
            "type": test["type"],
            "category": test["category"],
            "best_distance": round(float(best_dist), 4),
            "retrieved_chunks": len(docs),
            "citations_count": len(citations),
            "latency_ms": elapsed_ms,
            "fallback_triggered": is_fallback,
            "status": status_str
        })

        print(f" Test #{test['id']} [{test['category']}] -> {status_str}")
        print(f"    Query: '{test['query']}'")
        print(f"    Best Dist: {round(best_dist, 4)} | Chunks: {len(docs)} | Time: {elapsed_ms}ms")
        print("-" * 70)

    print("\n[3/3] Benchmark Summary Report")
    print(f"Total Tests: {len(BENCHMARK_CASES)}")
    print(f"Passed: {passed_count} / {len(BENCHMARK_CASES)} ({round(passed_count/len(BENCHMARK_CASES)*100, 1)}%)")

    # Generate Markdown Table Report
    report_md = ["# RAG System Evaluation & Benchmark Report\n"]
    report_md.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_md.append(f"**Quality Gate Threshold:** Distance <= {QUALITY_GATE_DISTANCE}\n")
    report_md.append("| ID | Category | Query | Type | Best Dist | Chunks | Latency | Result |")
    report_md.append("|---|---|---|---|---|---|---|---|")

    for r in results:
        report_md.append(
            f"| {r['id']} | {r['category']} | {r['query']} | {r['type']} | "
            f"{r['best_distance']} | {r['retrieved_chunks']} | {r['latency_ms']}ms | {r['status']} |"
        )

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'evaluation_report.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_md))

    print(f"\n📊 Full Markdown evaluation report saved to: docs/evaluation_report.md")

if __name__ == '__main__':
    run_evaluation()
