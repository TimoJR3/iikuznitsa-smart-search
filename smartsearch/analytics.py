"""Поисковые события: запись в SQLite и сводки для команды магазина."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_events (
    event_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    session_id TEXT,
    source TEXT NOT NULL,            -- demo | replay (прогон выборки организатора)
    query TEXT NOT NULL,
    normalized TEXT,
    expanded TEXT,
    corrections TEXT,
    intent TEXT,
    status TEXT NOT NULL,            -- ok | weak | no_match
    confidence REAL,
    llm_used INTEGER,
    llm_rewrite TEXT,
    n_results INTEGER,
    top_product_ids TEXT,
    top_title TEXT,
    top_category TEXT,
    latency_ms REAL
);
CREATE TABLE IF NOT EXISTS clicks (
    event_id TEXT, product_id INTEGER, position INTEGER, block TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS gap_labels (
    query TEXT PRIMARY KEY, label TEXT, note TEXT, ts TEXT
);
"""

GAP_LABELS = {
    "catalog_gap": "Нет в каталоге",
    "search_issue": "Проблема поиска",
    "unclear": "Недостаточно данных",
}


class Analytics:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def log_search(self, res: dict, session_id: str | None, source: str = "demo") -> str:
        u = res["understanding"]
        top = res["items"]
        eid = uuid.uuid4().hex
        with self._lock:
            self.db.execute(
                "INSERT INTO search_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, time.strftime("%Y-%m-%d %H:%M:%S"), session_id, source, res["query"], u["normalized"],
                 u["expanded"], json.dumps(u["corrections"], ensure_ascii=False), u["intent"], res["status"],
                 res["confidence"], int(res["llm_used"]), u["rewritten_by_llm"], len(top),
                 json.dumps([it["product_id"] for it in top[:10]]), top[0]["title"] if top else "",
                 top[0]["category"] if top else "", res["latency_ms"]),
            )
            self.db.commit()
        return eid

    def log_click(self, event_id: str, product_id: int, position: int, block: str) -> None:
        with self._lock:
            self.db.execute("INSERT INTO clicks VALUES (?,?,?,?,?)",
                            (event_id, product_id, position, block, time.strftime("%Y-%m-%d %H:%M:%S")))
            self.db.commit()

    def label_gap(self, query: str, label: str, note: str = "") -> None:
        if label not in GAP_LABELS:
            raise ValueError(label)
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO gap_labels VALUES (?,?,?,?)",
                            (query.strip().lower(), label, note, time.strftime("%Y-%m-%d %H:%M:%S")))
            self.db.commit()

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def summary(self, source: str | None = None) -> dict:
        where, args = ("WHERE source = ?", (source,)) if source else ("", ())
        tot = self._rows(f"""
            SELECT COUNT(*) AS searches, COUNT(DISTINCT lower(query)) AS unique_queries,
                   MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                   SUM(status = 'no_match') AS no_match, SUM(status = 'weak') AS weak,
                   SUM(llm_used) AS llm_used, SUM(corrections != '{{}}') AS corrected,
                   AVG(latency_ms) AS avg_latency_ms
            FROM search_events {where}""", args)[0]
        n = tot["searches"] or 0
        tot["no_match_share"] = round((tot["no_match"] or 0) / n, 3) if n else None
        tot["weak_share"] = round((tot["weak"] or 0) / n, 3) if n else None
        tot["understood_share"] = round(1 - ((tot["no_match"] or 0) + (tot["weak"] or 0)) / n, 3) if n else None
        clicks = self._rows("SELECT COUNT(*) AS clicks, COUNT(DISTINCT event_id) AS clicked_searches FROM clicks")[0]
        tot["ctr"] = round(clicks["clicked_searches"] / n, 3) if n else None
        tot["clicks_from_recommendations"] = self._rows(
            "SELECT COUNT(*) AS c FROM clicks WHERE block != 'results'")[0]["c"]
        top_q = self._rows(f"""
            SELECT lower(query) AS query, COUNT(*) AS n, MAX(top_title) AS top_title, MAX(status) AS status
            FROM search_events {where} GROUP BY lower(query) ORDER BY n DESC, query LIMIT 15""", args)
        gaps = self._rows(f"""
            SELECT lower(e.query) AS query, COUNT(*) AS n, ROUND(AVG(e.confidence), 2) AS confidence,
                   MAX(e.llm_rewrite) AS llm_rewrite, MAX(e.top_title) AS top_title, MAX(e.top_category) AS top_category,
                   g.label AS label, MAX(e.ts) AS last_ts
            FROM search_events e LEFT JOIN gap_labels g ON g.query = lower(e.query)
            {where + ' AND' if where else 'WHERE'} e.status IN ('no_match', 'weak')
            GROUP BY lower(e.query) ORDER BY n DESC, confidence LIMIT 30""", args)
        for g in gaps:
            g["label_text"] = GAP_LABELS.get(g["label"] or "", "Не размечено")
        intents = self._rows(f"SELECT intent, COUNT(*) AS n FROM search_events {where} GROUP BY intent", args)
        categories = self._rows(f"""
            SELECT top_category AS category, COUNT(*) AS n FROM search_events {where}
            {(where + ' AND') if where else 'WHERE'} status = 'ok' GROUP BY top_category ORDER BY n DESC LIMIT 10""", args)
        by_hour = self._rows(f"""
            SELECT substr(ts, 1, 13) AS hour, COUNT(*) AS n, SUM(status != 'ok') AS not_ok
            FROM search_events {where} GROUP BY hour ORDER BY hour""", args)
        recent = self._rows(f"""
            SELECT ts, query, status, confidence, llm_rewrite, top_title, latency_ms FROM search_events {where}
            ORDER BY ts DESC LIMIT 15""", args)
        return {"totals": tot, "top_queries": top_q, "gaps": gaps, "intents": intents,
                "categories": categories, "by_hour": by_hour, "recent": recent,
                "gap_labels": GAP_LABELS}
