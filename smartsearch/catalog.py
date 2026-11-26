"""Загрузка YML-фида store.softline.ru в таблицы товаров и категорий."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

OFFER_FIELDS = ("name", "vendor", "vendorUrl", "url", "price", "oldprice", "categoryId", "picture", "description")


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def parse_feed(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Потоково читает фид: возвращает (offers, categories)."""
    offers, categories = [], []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "category":
            categories.append({
                "category_id": int(el.get("id")),
                "parent_id": int(el.get("parentId")) if el.get("parentId") else None,
                "name": (el.text or "").strip(),
            })
            el.clear()
        elif el.tag == "offer":
            row = {f: _text(el, f) for f in OFFER_FIELDS}
            row["offer_id"] = int(el.get("id"))
            row["group_id"] = el.get("group_id") or _text(el, "group_id")
            row["available"] = el.get("available") == "true"
            params: dict[str, list[str]] = {}
            for p in el.findall("param"):
                params.setdefault(p.get("name", ""), []).append((p.text or "").strip())
            row["params"] = {k: "; ".join(v) for k, v in params.items()}
            offers.append(row)
            el.clear()
    off = pd.DataFrame(offers)
    off["price"] = pd.to_numeric(off["price"], errors="coerce").fillna(0.0)
    off["oldprice"] = pd.to_numeric(off["oldprice"], errors="coerce").fillna(0.0)
    off["categoryId"] = pd.to_numeric(off["categoryId"], errors="coerce").astype("Int64")
    off["product_type"] = off["params"].map(lambda p: p.get("Тип продукта", ""))
    off["vendor_slug"] = off["vendorUrl"].map(_vendor_slug)
    cat = pd.DataFrame(categories)
    return off, cat


def _vendor_slug(url: str) -> str:
    m = re.match(r"https?://store\.softline\.ru/([^/?#]+)/?", url or "")
    return m.group(1) if m else ""


_VARIANT_TAIL = re.compile(
    r"\s+(?:новая|продление|лицензи|подписк|электронн|сертификат|на\s+\d|для\s+\d|\d+\s*(?:пк|шт|мес|год|лет|пользоват|устройств)).*$",
    re.IGNORECASE,
)


_LEGAL = re.compile(r",?\s+(?:Ltd|Inc|LLC|GmbH|Corp|Co|AG|S\.A|s\.r\.o)\.?(?=[\s,(]|$)", re.IGNORECASE)
_VARIANT_WORDS = re.compile(r"лиценз|подпис|продлен|обновлен|\bна\s+\d|\d+\s*(?:год|мес|лет)|пользоват|верси|редакц|сертиф|ключ")


def base_title(name: str) -> str:
    """Название продукта без параметров варианта: срок, число мест, тип лицензии.

    «МТС Линк (Webinar Group) МТС Линк Стандарт (лицензия), на 1 год» -> «МТС Линк Стандарт»;
    «MDaemon Technologies, Ltd. MDaemon Messaging Server (продление…)» -> «MDaemon Technologies MDaemon Messaging Server».
    """
    s = _LEGAL.sub("", name.replace("&amp;", "&")).replace("«", "").replace("»", "").replace("®", "")
    s = re.sub(r"\s+", " ", s).strip()
    # Скобка-уточнение вендора посреди названия (без слов про вариант) выбрасывается, первая «вариантная» скобка — граница.
    while True:
        m = re.search(r"\(([^()]*)\)", s)
        if not m:
            break
        after = re.split(r"[(,]", s[m.end():], maxsplit=1)[0].strip()
        if not _VARIANT_WORDS.search(m.group(1).lower()) and len(after) >= 3:
            s = (s[: m.start()] + " " + s[m.end():]).strip()
            s = re.sub(r"\s+", " ", s)
            continue
        break
    title = re.split(r"\s*[(,]", s, maxsplit=1)[0]
    title = _VARIANT_TAIL.sub("", title).strip(" -–—.:")
    # «МТС Линк МТС Линк Стандарт» -> «МТС Линк Стандарт»: убираем повтор начала.
    words = title.split()
    for n in range(min(4, len(words) // 2), 0, -1):
        if words[:n] == words[n: 2 * n]:
            title = " ".join(words[n:])
            break
    return title or name.strip()


def build_products(off: pd.DataFrame, cat: pd.DataFrame) -> pd.DataFrame:
    """Сворачивает SKU в карточки продуктов: одна карточка на группу и базовое название.

    В выдачу попадают только товары в наличии с ценой: у остальных в фиде цена 0.
    """
    paths = category_paths(cat)
    a = off[off["available"] & (off["price"] > 0)].copy()
    a["title"] = a["name"].map(base_title)
    a["family"] = (
        a["group_id"].where(a["group_id"] != "", "o" + a["offer_id"].astype(str)) + "|" + a["title"].str.lower()
    )
    a["discount"] = ((a["oldprice"] - a["price"]) / a["oldprice"]).where(a["oldprice"] > a["price"], 0.0)
    a = a.sort_values(["family", "price"])
    rows = []
    for fam, g in a.groupby("family", sort=False):
        first = g.iloc[0]
        cid = int(first["categoryId"]) if pd.notna(first["categoryId"]) else -1
        path = paths.get(cid, [])
        rows.append({
            "family": fam,
            "title": first["title"],
            "vendor": first["vendor"],
            "vendor_slug": first["vendor_slug"],
            "category_id": cid,
            "category": path[-1] if path else "",
            "category_path": " > ".join(path),
            "root": path[0] if path else "",
            "product_type": first["product_type"],
            "min_price": float(g["price"].min()),
            "max_price": float(g["price"].max()),
            "n_offers": int(len(g)),
            "offer_id": int(first["offer_id"]),
            "url": first["url"],
            "picture": first["picture"],
            "description": first["description"][:300],
            "variants": " | ".join(g["name"].head(5)),
            "max_discount": float(g["discount"].max()),
            "registry": _first_param(g, "Номер записи в реестре отечественного ПО", digits=True),
            "certificate": _first_param(g, "Сертификаты и стандарты"),
            "oldprice": float(first["oldprice"]),
        })
    prod = pd.DataFrame(rows).reset_index(drop=True)
    prod.insert(0, "product_id", prod.index.astype(int))
    return prod


def _first_param(g: pd.DataFrame, name: str, digits: bool = False) -> str:
    """Первое осмысленное значение параметра среди вариантов продукта."""
    for params in g["params"]:
        v = (params.get(name) or "").strip()
        if not v or re.search(r"другое|отсутств|не определ|без сертификата", v, re.IGNORECASE):
            continue
        if digits and not re.fullmatch(r"\d+", v):
            continue
        return v
    return ""


def category_paths(cat: pd.DataFrame) -> dict[int, list[str]]:
    """Путь от корня до категории: id -> [корень, ..., категория]."""
    parent = dict(zip(cat["category_id"], cat["parent_id"]))
    name = dict(zip(cat["category_id"], cat["name"]))
    paths: dict[int, list[str]] = {}
    for cid in name:
        chain, cur, seen = [], cid, set()
        while cur is not None and cur in name and cur not in seen:
            seen.add(cur)
            chain.append(name[cur])
            p = parent.get(cur)
            cur = int(p) if p is not None and p == p else None
        paths[cid] = list(reversed(chain))
    return paths
