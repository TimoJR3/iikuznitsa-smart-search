"""Поисковый индекс: BM25 по словам, эмбеддинги по смыслу, словарь для исправления опечаток."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi

from .text import normalize, stems, tokens, translit

EMB_MODEL = "intfloat/multilingual-e5-small"


def doc_text(row: pd.Series) -> str:
    """Текст карточки для BM25: название весомее категории и вариантов."""
    return " ".join([
        row["title"], row["title"], row["title"], row["vendor"], row["vendor"],
        row["category"], row["category_path"], row["variants"],
    ])


def passage_text(row: pd.Series) -> str:
    """Текст карточки для эмбеддинга: что это за товар и где он лежит в каталоге."""
    kind = "оборудование" if row["product_type"] == "электроника" else "программное обеспечение"
    return f"passage: {row['title']}. {row['vendor']}. {kind}. {row['category_path']}"


_model = None


def embedder():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMB_MODEL, device="cpu")
    return _model


def embed(texts: list[str], batch_size: int = 64) -> np.ndarray:
    return embedder().encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False).astype(
        np.float32
    )


@dataclass
class SearchIndex:
    products: pd.DataFrame
    emb: np.ndarray
    bm25: BM25Okapi = field(init=False)
    vocab: Counter = field(init=False)
    vendor_names: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        docs = [stems(doc_text(r)) for _, r in self.products.iterrows()]
        self.bm25 = BM25Okapi(docs, k1=1.2, b=0.5)
        self.vocab = Counter(t for _, r in self.products.iterrows() for t in tokens(f"{r['title']} {r['vendor']} {r['category']}"))
        # Названия вендоров и их транслитерация — для запросов кириллицей к латинским брендам.
        self.vendor_names = {}
        for v in self.products["vendor"].unique():
            n = normalize(v)
            self.vendor_names[n] = v
            self.vendor_names[translit(n)] = v

    @classmethod
    def build(cls, products: pd.DataFrame, out_dir: Path) -> "SearchIndex":
        out_dir.mkdir(parents=True, exist_ok=True)
        t = time.time()
        emb = embed([passage_text(r) for _, r in products.iterrows()])
        products.to_parquet(out_dir / "products.parquet", index=False)
        np.save(out_dir / "emb.npy", emb)
        (out_dir / "meta.json").write_text(json.dumps({
            "model": EMB_MODEL, "products": len(products), "embed_seconds": round(time.time() - t, 1),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(products, emb)

    @classmethod
    def load(cls, out_dir: Path) -> "SearchIndex":
        return cls(pd.read_parquet(out_dir / "products.parquet"), np.load(out_dir / "emb.npy"))
