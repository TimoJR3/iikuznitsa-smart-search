"""Проверки на собранном индексе: python -m pytest -q (нужен data/index, см. README)."""

from __future__ import annotations

from pathlib import Path

import pytest

from smartsearch.catalog import base_title
from smartsearch.text import normalize, switch_layout

ROOT = Path(__file__).resolve().parents[1]
HAS_INDEX = (ROOT / "data/index/products.parquet").exists()


def test_base_title_drops_variant_and_vendor_alias():
    assert base_title("МТС Линк (Webinar Group) МТС Линк Стандарт (лицензия), на 1 год") == "МТС Линк Стандарт"
    assert base_title("AnyDesk (лицензия на 1 год), Solo") == "AnyDesk"
    assert base_title("Kaspersky Small Office Security новая лицензия на 5 ПК") == "Kaspersky Small Office Security"


def test_layout_and_normalize():
    assert switch_layout("fcnhf") == "астра"
    assert normalize("Ёлка «Про»") == "елка про"


@pytest.fixture(scope="module")
def search():
    if not HAS_INDEX:
        pytest.skip("индекс не собран")
    from smartsearch.index import SearchIndex
    from smartsearch.search import SmartSearch

    return SmartSearch(SearchIndex.load(ROOT / "data/index"), ROOT / "data/synonyms.json")


@pytest.mark.parametrize("query", ["astra linux", "мтс", "абракадабра", "anydesk", "сервер"])
def test_at_least_four_items(search, query):
    assert len(search.search(query, use_llm=False)["items"]) >= 4


def test_server_means_hardware_and_software_context(search):
    hw = search.search("сервер", use_llm=False)
    assert hw["understanding"]["intent"] == "hardware"
    assert hw["items"][0]["kind"] == "оборудование"
    sw = search.search("по для сервера", use_llm=False)
    assert sw["understanding"]["intent"] == "software"
    assert all(it["kind"] == "ПО" for it in sw["items"][:4])


@pytest.mark.parametrize("query,expected", [
    ("винда", "windows"), ("мдаемон", "mdaemon"), ("астра линукс", "astra linux"), ("fcnhf kbyerc", "astra linux"),
])
def test_jargon_typos_layout(search, query, expected):
    assert expected in search.search(query, use_llm=False)["items"][0]["title"].lower()


def test_upsell_blocks(search):
    r = search.search("astra linux", use_llm=False)
    assert r["bundles"] and all(b["items"] for b in r["bundles"])


def test_suggest_while_typing(search):
    r = search.suggest("мдаем")
    assert r["products"] and "mdaemon" in r["products"][0]["title"].lower()


def test_absent_product_gets_alternatives(search):
    r = search.search("teamviewer", use_llm=False)
    assert r["status"] == "absent" and r["understanding"]["absent"]["name"] == "TeamViewer"
    assert any("anydesk" in it["title"].lower() for it in r["items"][:4])


def test_domestic_filter(search):
    r = search.search("российский антивирус", use_llm=False)
    assert "dr.web" in r["items"][0]["title"].lower() or "kaspersky" in r["items"][0]["title"].lower()


def test_verified_recommendations_have_sources(search):
    r = search.search("astra linux", use_llm=False)
    verified = [x for b in r["bundles"] for x in b["items"] if x.get("fact")]
    assert verified and all(x["fact"]["url"].startswith("https://") for x in verified)


def test_registry_badge(search):
    r = search.search("astra linux", use_llm=False)
    assert any(b["type"] == "registry" for b in r["items"][0]["badges"])
