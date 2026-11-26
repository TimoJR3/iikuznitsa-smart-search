"""Собирает индекс из YML-фида: python scripts/build_index.py --feed data/raw/Mindbox.yml.gz.xml"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smartsearch.catalog import build_products, parse_feed  # noqa: E402
from smartsearch.index import SearchIndex  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", type=Path, default=Path("data/raw/Mindbox.yml.gz.xml"))
    ap.add_argument("--out", type=Path, default=Path("data/index"))
    args = ap.parse_args()
    t = time.time()
    off, cat = parse_feed(args.feed)
    print(f"Фид: {len(off)} SKU, {len(cat)} категорий, {time.time() - t:.1f} с")
    prod = build_products(off, cat)
    print(f"Карточек продуктов в наличии: {len(prod)} (из {int(off['available'].sum())} SKU в наличии)")
    t = time.time()
    SearchIndex.build(prod, args.out)
    print(f"Индекс собран за {time.time() - t:.1f} с -> {args.out}")


if __name__ == "__main__":
    main()
