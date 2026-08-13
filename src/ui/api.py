"""
api.py — FastAPI Web Sunucusu: Crisis RAG Web Arayüzü

BAŞLATMA (Proje dizininden):
    python src/ui/api.py

Tarayıcıda: http://localhost:8000
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# ── Path ayarı ──────────────────────────────────────────────────────────────
# api.py      → R:/Code/.../src/ui/api.py
# SRC_DIR     → R:/Code/.../src
# PROJECT_DIR → R:/Code/...
# WEB_DIR     → R:/Code/.../web
API_FILE    = Path(__file__).resolve()
UI_DIR      = API_FILE.parent
SRC_DIR     = UI_DIR.parent
PROJECT_DIR = SRC_DIR.parent
WEB_DIR     = PROJECT_DIR / "web"

sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SRC_DIR / "logic"))
sys.path.insert(0, str(SRC_DIR / "core"))

from generator import setup_system, answer_query_generator

import collections
from datetime import datetime

class InMemoryLogHandler(logging.Handler):
    def __init__(self, max_records: int = 500):
        super().__init__()
        self.records = collections.deque(maxlen=max_records)

    def emit(self, record):
        try:
            msg = self.format(record)
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": msg
            }
            self.records.append(log_entry)
        except Exception:
            self.handleError(record)

    def get_logs(self):
        return list(self.records)

    def clear(self):
        self.records.clear()

class EndpointLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not ("/api/logs" in msg or "/api/status" in msg)

logging.getLogger("uvicorn.access").addFilter(EndpointLogFilter())

in_memory_log_handler = InMemoryLogHandler()
in_memory_log_handler.setFormatter(logging.Formatter("%(message)s"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.getLogger().addHandler(in_memory_log_handler)
log = logging.getLogger("crisis_rag")

app = FastAPI(
    title="Crisis RAG API",
    description="Çevrim Dışı Kriz Asistanı — Yerel LLM Web API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Statik dosyalar ─────────────────────────────────────────────────────────────
app.mount("/css",    StaticFiles(directory=str(WEB_DIR / "css")),    name="css")
app.mount("/js",     StaticFiles(directory=str(WEB_DIR / "js")),     name="js")
app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# ── Uygulama durumu (paylaşılan state) ──────────────────────────────────────
app_state: dict = {
    "model":         None,
    "embeddings":    None,
    "db":            None,
    "state_manager": None,
    "query_cache":   {},
    "last_rag_docs": [],
    "chat_history":  [],
    "ready":         False,
    "loading":       False,
}

_model_ready_event = asyncio.Event()

def _initialize_system(loop: asyncio.AbstractEventLoop):
    """Blocking LLM + Embedding + DB load (runs in thread pool)"""
    log.info("Model, Embedding ve DB yukleniyor...")
    model, embeddings, db, query_cache, state_manager = setup_system()
    app_state["model"]         = model
    app_state["embeddings"]    = embeddings
    app_state["db"]            = db
    app_state["query_cache"]   = query_cache
    app_state["state_manager"] = state_manager
    app_state["ready"]         = True
    app_state["loading"]       = False
    log.info("=" * 55)
    log.info("  [+] SİSTEM BAŞARILI ŞEKİLDE YÜKLENDİ - LLM HAZIR!")
    log.info("=" * 55)
    loop.call_soon_threadsafe(_model_ready_event.set)

@app.on_event("startup")
async def startup():
    from state_manager import StateManager
    log.info("=" * 55)
    log.info("  Crisis RAG — Web Sunucusu Başladı")
    log.info(f"  Statik dosyalar: {WEB_DIR}")
    log.info("  Envanter sistemi bağımsız olarak başlatıldı.")
    # Initialize StateManager immediately so inventory works before LLM is loaded
    app_state["state_manager"] = StateManager()
    log.info("  Model yükleme başlatıldı (arkaplanda)...")
    log.info("=" * 55)
    app_state["loading"] = True
    loop = asyncio.get_running_loop()
    asyncio.create_task(asyncio.to_thread(_initialize_system, loop))

@app.on_event("shutdown")
async def shutdown():
    if app_state["db"]:
        app_state["db"].close()
        log.info("DB bağlantısı kapatıldı.")
    if app_state["model"]:
        try:
            app_state["model"].unload()
        except:
            pass

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>web/index.html bulunamadı</h1>", status_code=404)
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"), media_type="text/html; charset=utf-8")

@app.get("/api/status")
async def get_status():
    from core.config import DB_PATH
    db_exists = Path(DB_PATH).exists()

    status_str = "ready" if app_state["ready"] else ("loading" if app_state["loading"] else "not_loaded")

    return JSONResponse({
        "server":  "online",
        "model":   status_str,
        "db":      "connected" if (app_state["db"] or db_exists) else "not_found",
        "db_path": str(DB_PATH),
        "web_dir": str(WEB_DIR),
        "version": "1.0.0 (FastAPI + SSE Stream)",
    })

@app.get("/api/status/stream")
async def get_status_stream():
    """
    SSE push stream that notifies the browser the exact millisecond LLM model finishes loading.
    Includes retry: 86400000 to prevent browser auto-reconnect loops.
    """
    async def event_generator():
        if app_state["ready"]:
            yield f"retry: 86400000\ndata: {json.dumps({'model': 'ready'})}\n\n"
            return
        try:
            await asyncio.wait_for(_model_ready_event.wait(), timeout=600.0)
            yield f"retry: 86400000\ndata: {json.dumps({'model': 'ready'})}\n\n"
        except asyncio.TimeoutError:
            yield f"retry: 86400000\ndata: {json.dumps({'model': 'timeout'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/chat")
async def post_chat(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return JSONResponse({"error": "Boş sorgu"}, status_code=400)

    if not app_state["ready"]:
        return JSONResponse({
            "error": "Model henüz yükleniyor, lütfen birkaç saniye sonra tekrar deneyin.",
            "status": "model_loading"
        }, status_code=503)

    def event_generator():
        log.info(f"💬 [SOHBET SORUSU] '{query}'")
        print(f"\n{'='*55}")
        print(f"  [WEB] Sorgu: {query!r}")
        print(f"{'='*55}")
        gen = answer_query_generator(
            user_question=query,
            model=app_state["model"],
            embeddings_model=app_state["embeddings"],
            db=app_state["db"],
            chat_history=app_state["chat_history"],
            query_cache=app_state["query_cache"],
            state_manager=app_state["state_manager"]
        )

        token_count = 0
        for payload in gen:
            p_type = payload.get("type")
            if p_type == "rag_docs":
                docs = payload.get("docs", [])
                app_state["last_rag_docs"] = docs
                log.info(f"🔍 [RAG ARAMA] Veritabanından {len(docs)} ilgili parça (chunk) getirildi.")
                print(f"(*) RAG panel guncellendi: {len(docs)} chunk SSE uzerinden gonderiliyor")
                for i, d in enumerate(docs, 1):
                    fname = d.get("source_file", "?")
                    dist  = d.get("distance", 0)
                    snip  = (d.get("text", "")[:60]).replace("\n", " ")
                    print(f"    [{i}] dist={dist:.4f} | {fname} | {snip!r}")
                data_json = json.dumps({"rag_docs": docs}, ensure_ascii=False)
                yield f"data: {data_json}\n\n"
            elif p_type == "telemetry":
                telem = payload.get("telemetry", {})
                app_state["last_telemetry"] = telem
                data_json = json.dumps({"telemetry": telem}, ensure_ascii=False)
                yield f"data: {data_json}\n\n"
            elif p_type == "token":
                token = payload.get("token", "")
                token_count += 1
                data_json = json.dumps({"token": token}, ensure_ascii=False)
                yield f"data: {data_json}\n\n"
            elif p_type == "done":
                log.info(f"⚡ [LLM YANITI COMPLETED] SSE akışı tamamlandı ({token_count} token iletildi).")
                print(f"(*) Stream tamamlandi — {token_count} token SSE uzerinden gonderildi")
                yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/rag-debug")
async def get_rag_debug():
    return JSONResponse({
        "chunks": app_state["last_rag_docs"],
        "count": len(app_state["last_rag_docs"])
    })

@app.get("/api/inventory")
async def get_inventory():
    if app_state["state_manager"]:
        return JSONResponse(app_state["state_manager"].get_inventory())
    return JSONResponse({})

@app.post("/api/inventory")
async def post_inventory(request: Request):
    body = await request.json()
    item = body.get("item", "").strip()
    action = body.get("action", "add")
    amount = body.get("amount", 1)

    if not item or not app_state["state_manager"]:
        return JSONResponse({"error": "Gereksiz istek"}, status_code=400)

    log.info(f"📦 [ENVANTER İŞLEMİ] Eylem: {action.upper()} | Malzeme: '{item}' | Miktar: {amount}")

    if action == "delete":
        app_state["state_manager"].remove_inventory_direct({item: amount})
    else:
        app_state["state_manager"].update_inventory_direct({item: amount})

    return JSONResponse(app_state["state_manager"].get_inventory())

@app.delete("/api/inventory")
async def delete_inventory():
    if app_state["state_manager"]:
        app_state["state_manager"].clear()
        return JSONResponse({"status": "cleared"})
    return JSONResponse({"status": "no_state_manager"})

@app.get("/api/logs")
async def get_logs():
    return JSONResponse({
        "logs": in_memory_log_handler.get_logs(),
        "count": len(in_memory_log_handler.get_logs())
    })

@app.post("/api/logs")
async def post_log(request: Request):
    body = await request.json()
    msg = body.get("message", "").strip()
    if msg:
        log.info(msg)
    return JSONResponse({"status": "ok"})

@app.delete("/api/logs")
async def delete_logs():
    in_memory_log_handler.clear()
    log.info("Sistem günlükleri kullanıcı tarafından temizlendi.")
    return JSONResponse({"status": "cleared"})

@app.get("/api/library/list")
async def get_library_list():
    """
    Returns a list of available TXT and PDF files for the AI-bypass library reader.
    Categorizes files into 'rehber' (Guidance), 'masal' (Stories/Books), and 'pdf' (PDF Docs).
    """
    files = []
    raw_txts_dir = PROJECT_DIR / "data" / "raw_txts"
    raw_pdfs_dir = PROJECT_DIR / "data" / "raw_pdfs"
    pdfs_dir     = PROJECT_DIR / "data" / "pdfs"
    stories_dir  = PROJECT_DIR / "data" / "stories"
    books_dir    = PROJECT_DIR / "data" / "books"

    for d in (stories_dir, books_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Stories / Books (Masallar Tab)
    for d in (stories_dir, books_dir):
        if d.exists():
            for p in sorted(list(d.glob("*.txt")) + list(d.glob("*.pdf"))):
                if not any(f["name"] == p.name for f in files):
                    ftype = "pdf" if p.suffix.lower() == ".pdf" else "txt"
                    files.append({
                        "name": p.name,
                        "type": ftype,
                        "category": "masal",
                        "size": p.stat().st_size,
                    })

    # 2. Afet Rehberleri (TXT Tab)
    if raw_txts_dir.exists():
        for p in sorted(raw_txts_dir.glob("*.txt")):
            if not any(f["name"] == p.name for f in files):
                files.append({
                    "name": p.name,
                    "type": "txt",
                    "category": "rehber",
                    "size": p.stat().st_size,
                })

    # 3. PDF Dokümanları (PDF Tab)
    for pdf_dir in (raw_pdfs_dir, pdfs_dir):
        if pdf_dir.exists():
            for p in sorted(pdf_dir.glob("*.pdf")):
                if not any(f["name"] == p.name for f in files):
                    files.append({
                        "name": p.name,
                        "type": "pdf",
                        "category": "pdf",
                        "size": p.stat().st_size,
                    })

    return JSONResponse({"files": files, "count": len(files)})

@app.get("/api/child-stories")
async def get_child_stories():
    """
    Reads calming children stories from data/kisa_hikayeler directory and returns them to web frontend.
    """
    stories_dir = PROJECT_DIR / "data" / "kisa_hikayeler"
    stories = []
    if stories_dir.exists():
        for p in sorted(stories_dir.glob("*.txt")):
            try:
                content = p.read_text(encoding="utf-8").strip()
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                title = lines[0] if lines else p.stem.replace("_", " ").title()
                body = "\n\n".join(lines[1:]) if len(lines) > 1 else content
                stories.append({
                    "id": p.stem,
                    "title": title,
                    "content": body,
                    "filename": p.name
                })
            except Exception as e:
                log.warning(f"Hikaye okuma hatası {p.name}: {e}")

    return JSONResponse({"stories": stories, "count": len(stories)})

@app.get("/api/file/{filename}")
async def get_raw_file(filename: str):
    """
    Returns full content of a raw TXT file or extracts ALL pages from a PDF file for viewing in browser.
    """
    log.info(f"📖 [KÜTÜPHANE OKUYUCU] Belge görüntülendi: '{filename}'")
    raw_txts_dir = PROJECT_DIR / "data" / "raw_txts"
    raw_pdfs_dir = PROJECT_DIR / "data" / "raw_pdfs"
    pdfs_dir     = PROJECT_DIR / "data" / "pdfs"
    stories_dir  = PROJECT_DIR / "data" / "stories"
    kisa_dir     = PROJECT_DIR / "data" / "kisa_hikayeler"
    books_dir    = PROJECT_DIR / "data" / "books"

    # 1. TXT Search
    txt_path = raw_txts_dir / filename
    if not txt_path.exists():
        for d in (raw_txts_dir, stories_dir, kisa_dir, books_dir):
            if d.exists():
                for p in d.glob("*.txt"):
                    if p.name.lower() == filename.lower():
                        txt_path = p
                        break
                if txt_path.exists():
                    break

    if txt_path.exists() and txt_path.is_file():
        content = txt_path.read_text(encoding="utf-8", errors="replace")
        return JSONResponse({"filename": txt_path.name, "type": "txt", "content": content})

    # 2. PDF Search (check raw_pdfs, pdfs, stories, books)
    pdf_path = raw_pdfs_dir / filename
    if not pdf_path.exists():
        for d in (raw_pdfs_dir, pdfs_dir, stories_dir, books_dir):
            if d.exists():
                for p in d.glob("*.pdf"):
                    if p.name.lower() == filename.lower():
                        pdf_path = p
                        break
                if pdf_path.exists():
                    break

    if pdf_path.exists() and pdf_path.is_file():
        try:
            import pypdf
            reader = pypdf.PdfReader(pdf_path)
            num_pages = len(reader.pages)
            pages_text = []
            for i, page in enumerate(reader.pages):
                ptxt = (page.extract_text() or "").strip()
                if not ptxt:
                    ptxt = f"[Sayfa {i+1} metin içermiyor veya taranmış görsel formatında]"
                pages_text.append(f"--- SAYFA {i+1} / {num_pages} ---\n{ptxt}")
            full_text = "\n\n".join(pages_text) if pages_text else f"[PDF İçeriği Okunamadı - {num_pages} sayfa]"
            return JSONResponse({"filename": pdf_path.name, "type": "pdf", "num_pages": num_pages, "content": full_text})
        except Exception as e:
            return JSONResponse({"filename": pdf_path.name, "type": "pdf", "content": f"[PDF Belgesi] {pdf_path.name}\nSayfa okuma hatası: {e}\nBoyut: {pdf_path.stat().st_size} byte"})

    return JSONResponse({"error": f"'{filename}' dosyası bulunamadı"}, status_code=404)


@app.post("/api/shutdown")
async def shutdown_server():
    """
    Triggers graceful shutdown of the API server.
    """
    print("\n[+] [API SHUTDOWN] Güvenli kapatma emri alındı. Kriz asistanı sunucusu kapatılıyor...")
    os._exit(0)


def _cli_shutdown_listener():
    """
    Listens on CMD stdin for 'q', 'exit', 'kapat', 'cikis' to cleanly shut down api.py.
    """
    import sys, time
    time.sleep(1.0)
    print("\n" + "="*60)
    print("[*] SUNUCU HAZIR! Kapatmak için CMD terminaline 'q', 'kapat', 'cikis' yazabilirsiniz.")
    print("="*60 + "\n")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            cmd = line.strip().lower()
            if cmd in ('q', 'quit', 'exit', 'kapat', 'cikis', 'çıkış'):
                print("\n[+] [CLI SHUTDOWN] Güvenli kapatma emri alındı. Sunucu kapatılıyor...")
                os._exit(0)
        except Exception:
            break


if __name__ == "__main__":
    import threading
    threading.Thread(target=_cli_shutdown_listener, daemon=True).start()
    uvicorn.run(
        "api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
