"""HTTP-API и страница демо: поиск для покупателя и аналитика для команды магазина."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smartsearch.analytics import Analytics  # noqa: E402
from smartsearch.index import SearchIndex  # noqa: E402
from smartsearch.llm import GigaChatRewriter  # noqa: E402
from smartsearch.search import SmartSearch  # noqa: E402

DATA = Path(os.getenv("DATA_DIR", ROOT / "data"))
RUNTIME = Path(os.getenv("RUNTIME_DIR", DATA / "runtime"))
RUNTIME.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Умный поиск store.softline.ru — прототип ИИкузницы", version="0.1.0")
state: dict = {}


@app.on_event("startup")
def startup() -> None:
    t = time.time()
    ix = SearchIndex.load(DATA / "index")
    llm = GigaChatRewriter.from_env(RUNTIME)
    s = SmartSearch(ix, DATA / "synonyms.json", llm=llm)
    s.warmup()
    s.search("astra linux", use_llm=False)  # прогрев модели эмбеддингов
    state.update(search=s, analytics=Analytics(RUNTIME / "analytics.db"), llm=llm is not None,
                 started=time.strftime("%Y-%m-%d %H:%M:%S"), load_s=round(time.time() - t, 1))


@app.get("/health")
def health() -> dict:
    s: SmartSearch | None = state.get("search")
    return {"status": "ok" if s else "starting", "products": len(s.p) if s else 0, "llm": state.get("llm"),
            "started": state.get("started"), "load_s": state.get("load_s")}


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1, max_length=200), session: str | None = None,
               limit: int = Query(12, ge=4, le=40)) -> dict:
    res = state["search"].search(q, limit=limit)
    res["event_id"] = state["analytics"].log_search(res, session)
    return res


@app.get("/api/suggest")
def api_suggest(q: str = Query("", max_length=200)) -> dict:
    return state["search"].suggest(q)


class Click(BaseModel):
    event_id: str
    product_id: int
    position: int = 0
    block: str = "results"


@app.post("/api/click")
def api_click(c: Click) -> dict:
    state["analytics"].log_click(c.event_id, c.product_id, c.position, c.block)
    return {"ok": True}


class GapLabel(BaseModel):
    query: str
    label: str
    note: str = ""


@app.post("/api/gaps/label")
def api_label(g: GapLabel) -> dict:
    try:
        state["analytics"].label_gap(g.query, g.label, g.note)
    except ValueError:
        raise HTTPException(400, "unknown label") from None
    return {"ok": True}


@app.get("/api/analytics")
def api_analytics(source: str | None = None) -> JSONResponse:
    return JSONResponse(state["analytics"].summary(source))


@app.get("/api/product/{product_id}")
def api_product(product_id: int) -> dict:
    s: SmartSearch = state["search"]
    if not 0 <= product_id < len(s.p):
        raise HTTPException(404)
    card = s._card(product_id)
    card["bundles"] = s.recommend(product_id, exclude={product_id})
    card["alternatives"] = s.alternatives(product_id, exclude={product_id})
    return card


app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "app" / "static" / "index.html")
