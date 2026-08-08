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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
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

def _initialize_system():
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

@app.on_event("startup")
async def startup():
    log.info("=" * 55)
    log.info("  Crisis RAG — Web Sunucusu Başladı")
    log.info(f"  Statik dosyalar: {WEB_DIR}")
    log.info("  Model yükleme başlatıldı (arkaplanda)...")
    log.info("=" * 55)
    app_state["loading"] = True
    asyncio.create_task(asyncio.to_thread(_initialize_system))

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
    return HTMLResponse(index_path.read_text(encoding="utf-8"))

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
        gen = answer_query_generator(
            user_question=query,
            model=app_state["model"],
            embeddings_model=app_state["embeddings"],
            db=app_state["db"],
            chat_history=app_state["chat_history"],
            query_cache=app_state["query_cache"],
            state_manager=app_state["state_manager"]
        )

        for payload in gen:
            p_type = payload.get("type")
            if p_type == "rag_docs":
                docs = payload.get("docs", [])
                app_state["last_rag_docs"] = docs
                data_json = json.dumps({"rag_docs": docs}, ensure_ascii=False)
                yield f"data: {data_json}\n\n"
            elif p_type == "token":
                token = payload.get("token", "")
                data_json = json.dumps({"token": token}, ensure_ascii=False)
                yield f"data: {data_json}\n\n"
            elif p_type == "done":
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

if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
