"""Сравнение поиска по точному совпадению и умного поиска на эталонных запросах.

python scripts/evaluate.py  ->  eval/results.md, eval/results.csv
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smartsearch.index import SearchIndex  # noqa: E402
from smartsearch.search import SmartSearch  # noqa: E402
from smartsearch.text import normalize, tokens  # noqa: E402

K = 4  # по ТЗ в ответе минимум 4 товара


def baseline(prod: pd.DataFrame, text: list[str], query: str, k: int = 12) -> list[int]:
    """Модель текущего поиска: все слова запроса как подстроки в названии или описании."""
    q = tokens(normalize(query))
    if not q:
        return []
    hits = [i for i, t in enumerate(text) if all(w in t for w in q)]
    titles = prod["title"].str.lower().to_numpy()
    hits.sort(key=lambda i: -sum(w in titles[i] for w in q))
    return hits[:k]


def is_hit(row: pd.Series, item: dict, prod: pd.DataFrame) -> bool:
    p = prod.loc[item["product_id"]]
    if row["expect_vendor_slug"] and p["vendor_slug"] != row["expect_vendor_slug"]:
        return False
    if row["expect_title_regex"]:
        hay = normalize(f"{p['title']} {p['category_path']}")
        if not re.search(row["expect_title_regex"], hay):
            return False
    return item["kind"] == row["expect_kind"]


def main() -> None:
    ix = SearchIndex.load(ROOT / "data/index")
    s = SmartSearch(ix, ROOT / "data/synonyms.json")
    s.warmup()
    prod = ix.products
    text = (prod["title"] + " " + prod["description"] + " " + prod["variants"]).map(normalize).tolist()
    q = pd.read_csv(ROOT / "eval/queries.csv", keep_default_na=False)
    rows = []
    for _, r in q.iterrows():
        base_ids = baseline(prod, text, r["query"])
        base_items = [s._card(i) for i in base_ids]
        t = time.perf_counter()
        res = s.search(r["query"], use_llm=False)
        ms = (time.perf_counter() - t) * 1000
        items = res["items"]
        rows.append({
            "query": r["query"], "type": r["type"], "source": r["source"],
            "base_n": len(base_items),
            "base_hit1": bool(base_items) and is_hit(r, base_items[0], prod),
            "base_hit4": any(is_hit(r, it, prod) for it in base_items[:K]),
            "smart_n": len(items),
            "smart_hit1": bool(items) and is_hit(r, items[0], prod),
            "smart_hit4": any(is_hit(r, it, prod) for it in items[:K]),
            "smart_top1": items[0]["title"] if items else "",
            "confidence": res["confidence"],
            "latency_ms": round(ms, 1),
        })
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "eval/results.csv", index=False)
    official = df[df["source"] == "выборка организатора"]

    def summary(d: pd.DataFrame) -> dict:
        return {
            "запросов": len(d),
            "пустая выдача, точное совпадение": f"{(d['base_n'] == 0).mean():.0%}",
            "пустая выдача, умный поиск": f"{(d['smart_n'] == 0).mean():.0%}",
            "≥4 товаров, умный поиск": f"{(d['smart_n'] >= K).mean():.0%}",
            "Hit@1 точное / умный": f"{d['base_hit1'].mean():.0%} / {d['smart_hit1'].mean():.0%}",
            f"Hit@{K} точное / умный": f"{d['base_hit4'].mean():.0%} / {d['smart_hit4'].mean():.0%}",
        }

    lat = df["latency_ms"].to_numpy()
    lines = [
        "# Оценка поиска", "",
        f"Прогон {time.strftime('%Y-%m-%d %H:%M')}, каталог: {len(prod)} карточек продуктов в наличии. "
        "Точное совпадение — модель текущего поиска: все слова запроса должны встретиться в названии или описании.",
        "Попадание — в выдаче есть товар ожидаемого вендора, линейки и типа (ПО или оборудование). LLM в прогоне выключена.", "",
        "| Метрика | Выборка организатора | Все запросы |", "|---|---|---|",
    ]
    so, sa = summary(official), summary(df)
    for key in sa:
        lines.append(f"| {key} | {so[key]} | {sa[key]} |")
    lines += [
        f"| Задержка p50 / p95, мс | | {np.percentile(lat, 50):.0f} / {np.percentile(lat, 95):.0f} |", "",
        "## По запросам", "",
        "| Запрос | Тип | Точное: найдено / Hit@4 | Умный: Hit@1 / Hit@4 | Первый товар умного поиска |",
        "|---|---|---|---|---|",
    ]
    yes = lambda b: "✅" if b else "❌"  # noqa: E731
    for _, r in df.iterrows():
        lines.append(
            f"| {r['query']} | {r['type']} | {r['base_n']} / {yes(r['base_hit4'])} | "
            f"{yes(r['smart_hit1'])} / {yes(r['smart_hit4'])} | {r['smart_top1'][:60]} |"
        )
    (ROOT / "eval/results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
