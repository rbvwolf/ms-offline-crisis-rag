import os

# Absolute path of project root: src/core/config.py -> src/core -> src -> project root
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))

# --- Paths ---
DB_PATH = os.path.join(PROJECT_ROOT, "db", "survival_knowledge.db")
RAW_PDF_DIR = os.path.join(PROJECT_ROOT, "data", "raw_pdfs")

# --- Embedding Model ---
# Must stay in sync across ingestion, retrieval, and generation.
# Changing this constant alone is sufficient — no need to edit three files.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# --- Ingestion ---
MIN_CHUNK_LENGTH = 80       # chars — shorter chunks are considered garbage
CHUNK_SIZE = 750            # chars per chunk
CHUNK_OVERLAP = 100         # chars of overlap between consecutive chunks

# --- Retrieval ---
MAX_DISTANCE = 0.90         # chunks beyond this distance are discarded from context
QUALITY_GATE_DISTANCE = 0.90  # if even the best chunk exceeds this, return "not found"

# --- Generation ---
MAX_CONTEXT_CHARS = 2500    # hard cap on total context sent to the LLM
STREAM_TIMEOUT_SECONDS = 180  # hard time limit for streaming generation
