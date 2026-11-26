"""Поисковый индекс: BM25 по словам, эмбеддинги по смыслу, словарь для исправления опечаток."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

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


GROUPS = {
    "os": ("Операционные системы", {"Операционные системы", "Программы для macOS"}),
    "security": ("Безопасность", {"Антивирусы и безопасность", "Цифровые сертификаты", "Системы безопасности"}),
    "office": ("Офис и документы", {"Офисные программы", "Программы для работы с текстом", "Электронные книги",
                                    "Программы для образования и науки",
                                    "Программное обеспечение для дистанционного обучения"}),
    "design": ("САПР, графика, медиа", {"Программное обеспечение для графики и дизайна", "Мультимедиа",
                                       "Программы САПР и ГИС", "Карты, навигация, путешествия"}),
    "business": ("Бизнес и облака", {"Управление бизнесом, CRM/ERP", "Бухгалтерия. Склад. Кадры",
                                     "Облачные решения (SaaS)", "Сервисные решения", "ИИ", "Искусственный интеллект"}),
    "infra": ("Инфраструктура и сеть", {"Сеть и интернет", "Облачные решения (IaaS)", "Системные программы",
                                        "Программное обеспечение для работы с файлами и дисками",
                                        "Программы для удаленного доступа", "Программы для смартфонов"}),
    "dev": ("Разработка", {"Программы для программирования"}),
    "hardware": ("Оборудование", set()),
}


def product_group(root: str, product_type: str) -> str:
    if product_type == "электроника":
        return "hardware"
    for key, (_, roots) in GROUPS.items():
        if root in roots:
            return key
    return "infra"


def _tsne(emb: np.ndarray, seed: int) -> np.ndarray:
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE

    x = PCA(n_components=min(50, emb.shape[0] - 1), random_state=seed).fit_transform(emb)
    xy = TSNE(n_components=2, perplexity=30, init="pca", random_state=seed, metric="cosine").fit_transform(x)
    xy -= xy.min(axis=0)
    return xy / xy.max(axis=0)


# Два «материка» карты: программы слева, оборудование справа. Так ПО не теряется среди тысяч позиций железа.
CONTINENTS = {"software": (0.0, 0.0, 0.6, 1.0), "hardware": (0.66, 0.08, 1.0, 0.92)}


def map_coords(emb: np.ndarray, is_hw: np.ndarray, seed: int = 7) -> np.ndarray:
    """2D-карта каталога: близкие по смыслу продукты рядом. PCA(50) + t-SNE отдельно для ПО и оборудования."""
    xy = np.zeros((len(emb), 2), dtype=np.float32)
    for name, mask in (("software", ~is_hw), ("hardware", is_hw)):
        if mask.sum() < 3:
            continue
        x0, y0, x1, y1 = CONTINENTS[name]
        part = _tsne(emb[mask], seed)
        xy[mask, 0] = x0 + part[:, 0] * (x1 - x0)
        xy[mask, 1] = y0 + part[:, 1] * (y1 - y0)
    return xy


class SparseBM25:
    """BM25 на разреженной матрице: оценка запроса — сумма столбцов, единицы миллисекунд на 10 тыс. карточек."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.5) -> None:
        self.term_id: dict[str, int] = {}
        rows, cols, vals = [], [], []
        for d, doc in enumerate(docs):
            for t, tf in Counter(doc).items():
                rows.append(d)
                cols.append(self.term_id.setdefault(t, len(self.term_id)))
                vals.append(tf)
        tf = sparse.csr_matrix((vals, (rows, cols)), shape=(len(docs), len(self.term_id)), dtype=np.float32)
        dl = np.asarray(tf.sum(axis=1)).ravel()
        df = np.bincount(cols, minlength=len(self.term_id))
        idf = np.log(1 + (len(docs) - df + 0.5) / (df + 0.5)).astype(np.float32)
        norm = k1 * (1 - b + b * dl / dl.mean())
        tf = tf.tocoo()
        w = idf[tf.col] * tf.data * (k1 + 1) / (tf.data + norm[tf.row])
        self.w = sparse.csc_matrix((w, (tf.row, tf.col)), shape=tf.shape)

    def scores(self, query_terms: list[str]) -> np.ndarray:
        ids = [self.term_id[t] for t in query_terms if t in self.term_id]
        if not ids:
            return np.zeros(self.w.shape[0], dtype=np.float32)
        return np.asarray(self.w[:, ids].sum(axis=1)).ravel()


@dataclass
class SearchIndex:
    products: pd.DataFrame
    emb: np.ndarray
    xy: np.ndarray | None = None
    bm25: SparseBM25 = field(init=False)
    vocab: Counter = field(init=False)
    vendor_names: dict[str, str] = field(init=False)
    category_stems: list[set[str]] = field(init=False)

    def __post_init__(self) -> None:
        p = self.products
        p["group"] = [product_group(r, t) for r, t in zip(p["root"], p["product_type"])]
        if self.xy is None:
            self.xy = np.full((len(p), 2), 0.5, dtype=np.float32)
        self.bm25 = SparseBM25([stems(doc_text(r)) for _, r in p.iterrows()])
        self.vocab = Counter(t for _, r in p.iterrows() for t in tokens(f"{r['title']} {r['vendor']} {r['category']}"))
        self.category_stems = [set(stems(c.replace("-", " "))) for c in p["category"]]
        # Названия вендоров и их транслитерация — для запросов кириллицей к латинским брендам.
        self.vendor_names = {}
        for v in p["vendor"].unique():
            n = normalize(v)
            self.vendor_names[n] = v
            self.vendor_names[translit(n)] = v

    @classmethod
    def build(cls, products: pd.DataFrame, out_dir: Path) -> "SearchIndex":
        out_dir.mkdir(parents=True, exist_ok=True)
        t = time.time()
        emb = embed([passage_text(r) for _, r in products.iterrows()])
        t_emb = time.time() - t
        t = time.time()
        xy = map_coords(emb, (products["product_type"] == "электроника").to_numpy())
        products.to_parquet(out_dir / "products.parquet", index=False)
        np.save(out_dir / "emb.npy", emb)
        np.save(out_dir / "xy.npy", xy)
        (out_dir / "meta.json").write_text(json.dumps({
            "model": EMB_MODEL, "products": len(products), "embed_seconds": round(t_emb, 1),
            "map_seconds": round(time.time() - t, 1), "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(products, emb, xy)

    @staticmethod
    def rebuild_map(out_dir: Path) -> None:
        """Пересчитать только карту по сохранённым эмбеддингам."""
        p = pd.read_parquet(out_dir / "products.parquet")
        np.save(out_dir / "xy.npy", map_coords(np.load(out_dir / "emb.npy"), (p["product_type"] == "электроника").to_numpy()))

    @classmethod
    def load(cls, out_dir: Path) -> "SearchIndex":
        xy_path = out_dir / "xy.npy"
        return cls(pd.read_parquet(out_dir / "products.parquet"), np.load(out_dir / "emb.npy"),
                   np.load(xy_path) if xy_path.exists() else None)
