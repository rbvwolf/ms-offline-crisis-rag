import sqlite3
import sqlite_vec
import sys
sys.path.insert(0, '.')
from langchain_huggingface import HuggingFaceEmbeddings
from src.logic.retriever import open_db, _vector_search, _smart_fts_search, _reciprocal_rank_fusion, _prepare_fts_query

db = open_db()
emb = HuggingFaceEmbeddings(
    model_name='paraphrase-multilingual-MiniLM-L12-v2',
    encode_kwargs={'normalize_embeddings': True}
)
query = 'mors alfabesi mors alfabesi nokta cizgi harf kodu SOS sinyal'
vec = emb.embed_query(query)

VECTOR_K = 40
FTS_K = 40
RRF_K = 60

vec_results = _vector_search(vec, db, VECTOR_K)
fts_results = _smart_fts_search(query, db, FTS_K)
fused = _reciprocal_rank_fusion(vec_results, fts_results, RRF_K)

print("VEC RESULTS:", [r[0] for r in vec_results])
print("FTS RESULTS:", [r[0] for r in fts_results])
print("FUSED TOP 15:", [r[0] for r in fused[:15]])

vector_dist_map = {chunk_id: dist for chunk_id, dist in vec_results}
print(f"DIST FOR 3442: {vector_dist_map.get(3442, 0.85)}")
