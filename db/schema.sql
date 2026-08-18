-- Offline Crisis RAG - SQLite Schema Definition
-- Combines Dense Vector Search (sqlite-vec) with Lexical Full-Text Search (FTS5)

-- 1. sqlite-vec Dense Vector Virtual Table (384-dim for paraphrase-multilingual-MiniLM-L12-v2)
CREATE VIRTUAL TABLE IF NOT EXISTS survival_vectors USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    text TEXT,
    embedding float[384]
);

-- 2. Metadata Table for Source Provenance and Page Tracking
CREATE TABLE IF NOT EXISTS chunks_metadata(
    chunk_id INTEGER PRIMARY KEY,
    source_file TEXT,
    page_number INTEGER,
    source_type TEXT DEFAULT 'pdf'
);

-- 3. FTS5 Lexical Search Table for BM25 Keyword Matching (with Turkish diacritic removal)
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    chunk_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
