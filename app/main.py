"""HTTP-API и страница демо: поиск для покупателя и аналитика для команды магазина."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smartsearch.analytics import Analytics  # noqa: E402
from smartsearch.index import GROUPS, SearchIndex  # noqa: E402
from smartsearch.llm import GigaChatRewriter  # noqa: E402
from smartsearch.search import SmartSearch  # noqa: E402

log = logging.getLogger("smartsearch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DATA = Path(os.getenv("DATA_DIR", ROOT / "data"))
SEED = DATA / "runtime"


def writable_runtime() -> Path:
    """Папка для журнала и кеша. Если файловая система образа только для чтения
    (так бывает в контейнерных платформах), переходим во временную папку и копируем туда
    журнал с прогоном выборки магазина."""
    for cand in [Path(os.getenv("RUNTIME_DIR", SEED)), Path(tempfile.gettempdir()) / "smart-search-runtime"]:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError:
            continue
        if cand != SEED and (SEED / "analytics.db").exists() and not (cand / "analytics.db").exists():
            shutil.copy2(SEED / "analytics.db", cand / "analytics.db")
        return cand
    raise RuntimeError("нет доступной для записи папки")


RUNTIME = writable_runtime()

app = FastAPI(title="Умный поиск store.softline.ru — прототип ИИкузницы", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)
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
    log.info("готово за %.1f с, журнал: %s, потоков torch: %s", time.time() - t, RUNTIME, _threads())


def _threads() -> int:
    try:
        import torch

        return torch.get_num_threads()
    except Exception:
        return -1


@app.get("/health")
def health() -> dict:
    s: SmartSearch | None = state.get("search")
    return {"status": "ok" if s else "starting", "products": len(s.p) if s else 0, "llm": state.get("llm"),
            "started": state.get("started"), "load_s": state.get("load_s")}


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1, max_length=200), session: str | None = None,
               limit: int = Query(12, ge=4, le=40)) -> dict:
    res = state["search"].search(q, limit=limit)
    try:
        res["event_id"] = state["analytics"].log_search(res, session)
    except Exception:  # журнал не должен ломать поиск покупателю
        log.exception("не удалось записать событие поиска")
        res["event_id"] = None
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


@app.get("/api/map")
def api_map() -> Response:
    """Вся карта каталога одним ответом: координаты, группа, название, вендор, цена. Кешируется на старте."""
    if "map_json" not in state:
        s: SmartSearch = state["search"]
        p, xy = s.p, s.ix.xy
        payload = {
            "groups": {k: v[0] for k, v in GROUPS.items()},
            "points": [
                [int(i), round(float(xy[i][0]), 4), round(float(xy[i][1]), 4), g, t[:90], v[:40], round(pr)]
                for i, (g, t, v, pr) in enumerate(zip(p["group"], p["title"], p["vendor"], p["min_price"]))
            ],
        }
        state["map_json"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return Response(state["map_json"], media_type="application/json",
                    headers={"Cache-Control": "no-cache"})


@app.get("/api/analytics/map")
def api_analytics_map(source: str | None = None) -> list[dict]:
    """Запросы на карте каталога: где спрос, и где он не находит товара."""
    s: SmartSearch = state["search"]
    where, args = ("WHERE source = ?", (source,)) if source else ("", ())
    rows = state["analytics"]._rows(f"""
        SELECT lower(query) AS query, COUNT(*) AS n, MIN(status) AS status, AVG(confidence) AS confidence,
               MAX(top_product_ids) AS ids FROM search_events {where} GROUP BY lower(query)""", args)
    out = []
    for r in rows:
        ids = [i for i in json.loads(r.pop("ids") or "[]") if 0 <= i < len(s.p)]
        r["xy"] = s.query_xy(ids)
        r["confidence"] = round(r["confidence"] or 0, 2)
        out.append(r)
    return out


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
