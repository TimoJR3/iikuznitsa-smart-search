"""Прогоняет выборку запросов организатора и эталонный набор через поиск и пишет события с source=replay.

Так вкладка «Аналитика» с первого запуска показывает картину по реальным запросам магазина,
а события живого демо (source=demo) остаются отдельно.
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smartsearch.analytics import Analytics  # noqa: E402
from smartsearch.index import SearchIndex  # noqa: E402
from smartsearch.llm import GigaChatRewriter  # noqa: E402
from smartsearch.search import SmartSearch  # noqa: E402


def organizer_queries(path: Path) -> list[str]:
    ws = openpyxl.load_workbook(path, read_only=True).active
    return [str(r[0]).strip() for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0] is not None]


def main() -> None:
    runtime = ROOT / "data/runtime"
    s = SmartSearch(SearchIndex.load(ROOT / "data/index"), ROOT / "data/synonyms.json",
                    llm=GigaChatRewriter.from_env(runtime))
    an = Analytics(runtime / "analytics.db")
    an.db.execute("DELETE FROM search_events WHERE source = 'replay'")
    an.db.commit()
    queries = []
    xlsx = ROOT / "data/raw/Выборка поисковых запросов.xlsx"
    if xlsx.exists():
        queries += organizer_queries(xlsx)
    queries += pd.read_csv(ROOT / "eval/queries.csv", keep_default_na=False)["query"].tolist()
    for q in dict.fromkeys(queries):
        res = s.search(q)
        an.log_search(res, session_id="replay", source="replay")
        print(f"{res['status']:8} {res['confidence']:.2f} {q!r} -> {res['items'][0]['title'] if res['items'] else '-'}")


if __name__ == "__main__":
    main()
