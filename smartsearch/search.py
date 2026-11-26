"""Умный поиск: понимание запроса, гибридный отбор, намерение «оборудование или ПО», допродажа."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz, process

from .index import SearchIndex, embed
from .text import STOP, has_cyr, normalize, stem, stems, switch_layout, tokens, translit

MIN_RESULTS = 4
GENERIC = {stem(w) for w in "программа программы приложение софт решение система работы работа купить нужен нужна "
           "нужно хочу лучший лучшая хороший недорогой дешевый чем как что".split()}
RRF_K = 60

HARDWARE_WORDS = {
    "сервер", "серверы", "серверное", "серверная", "оборудование", "железо", "ноутбук", "ноутбуки", "монитор", "мониторы",
    "ибп", "коммутатор", "коммутаторы", "маршрутизатор", "принтер", "принтеры", "мфу", "компьютер", "моноблок",
    "ssd", "hdd", "диск", "память", "процессор", "клавиатура", "мышь", "наушники", "кресло", "стойка", "схд",
    "rack", "tower", "картридж", "сканер", "проектор", "камера", "планшет", "смартфон", "роутер",
}
SOFTWARE_WORDS = {
    "по", "программа", "программы", "программное", "лицензия", "лицензии", "подписка", "ос", "linux", "windows",
    "антивирус", "office", "софт", "почтовый", "1с", "субд", "виртуализация", "бэкап", "резервное", "astra", "для",
    "защита", "mdaemon", "kaspersky", "dr.web", "криптопро",
}
# Слова, которые сами по себе означают и железо, и ПО: решаем по контексту.
AMBIGUOUS = {"сервер", "серверы", "серверное", "сканер", "диск"}

# Сопутствующие решения по корневой категории найденного товара: (запрос в каталог, подпись блока).
COMPLEMENTS: dict[str, list[tuple[str, str]]] = {
    "Операционные системы": [
        ("антивирус для организаций", "Защита рабочих мест"),
        ("средство защиты информации secret net", "Информационная безопасность"),
        ("кибер бэкап резервное копирование", "Резервное копирование"),
        ("российское офисное по", "Офисный пакет"),
    ],
    "Антивирусы и безопасность": [
        ("кибер бэкап резервное копирование", "Резервное копирование"),
        ("российская операционная система astra linux", "Операционная система"),
        ("сканер уязвимостей", "Анализ защищённости"),
        ("криптопро csp", "Электронная подпись"),
    ],
    "Офисные программы": [
        ("антивирус для организаций", "Защита рабочих мест"),
        ("почтовый сервер", "Почта"),
        ("pdf редактор", "Работа с PDF"),
        ("операционная система windows 11", "Операционная система"),
    ],
    "Серверы и опции": [
        ("серверная операционная система", "ОС для сервера"),
        ("виртуализация", "Виртуализация"),
        ("кибер бэкап резервное копирование", "Резервное копирование"),
        ("ибп источник бесперебойного питания", "Питание"),
    ],
    "Программное обеспечение для работы с файлами и дисками": [
        ("система хранения данных", "Хранение"),
        ("антивирус для организаций", "Защита"),
        ("российская операционная система astra linux", "Операционная система"),
    ],
    "Программы для удаленного доступа": [
        ("антивирус для организаций", "Защита"),
        ("vpn", "Защищённое подключение"),
        ("мтс линк", "Видеосвязь"),
    ],
    "Сеть и интернет": [
        ("антивирус для организаций", "Защита"),
        ("программы для удаленного доступа", "Удалённый доступ"),
        ("почтовый сервер", "Почта"),
    ],
    "Компьютеры": [
        ("операционная система windows 11", "Операционная система"),
        ("microsoft office", "Офисный пакет"),
        ("антивирус", "Защита"),
        ("монитор", "Периферия"),
    ],
    "Портативные компьютеры": [
        ("операционная система windows 11", "Операционная система"),
        ("microsoft office", "Офисный пакет"),
        ("антивирус", "Защита"),
        ("мышь", "Периферия"),
    ],
    "Сетевое оборудование": [
        ("межсетевой экран", "Сетевая безопасность"),
        ("ибп источник бесперебойного питания", "Питание"),
        ("кабели", "Кабели"),
    ],
}
DEFAULT_COMPLEMENTS = [
    ("антивирус для организаций", "Защита"),
    ("кибер бэкап резервное копирование", "Резервное копирование"),
]


@dataclass
class Understanding:
    raw: str
    normalized: str
    layout_fixed: bool = False
    corrections: dict[str, str] = field(default_factory=dict)
    expansions: list[str] = field(default_factory=list)
    intent: str = "any"  # hardware | software | any
    intent_reason: str = ""
    vendors: list[str] = field(default_factory=list)
    rewritten_by_llm: str = ""

    @property
    def expanded(self) -> str:
        parts = [self.normalized, *self.corrections.values(), *self.expansions]
        return " ".join(dict.fromkeys(p for p in parts if p))


class SmartSearch:
    def __init__(self, index: SearchIndex, synonyms_path: Path, llm=None) -> None:
        self.ix = index
        self.p = index.products
        raw = json.loads(synonyms_path.read_text(encoding="utf-8"))
        self.synonyms = {k: v for k, v in raw.items() if not k.startswith("_")}
        self.vocab_keys = [w for w, c in index.vocab.items() if len(w) >= 3 and not w.isdigit()]
        self.vocab_set = set(index.vocab)
        self.is_hw = (self.p["product_type"] == "электроника").to_numpy()
        self.llm = llm
        titles = self.p["title"].map(normalize)
        self._titles = titles.tolist()
        self._vendor_norm = self.p["vendor"].map(normalize).to_numpy()
        self._quick_cache: dict[str, list[int]] = {}

    # ---------- понимание запроса ----------
    def understand(self, query: str) -> Understanding:
        u = Understanding(raw=query, normalized=normalize(query))
        toks = tokens(u.normalized)
        known = sum(t in self.vocab_set or t in self.synonyms for t in toks)
        if toks and known == 0:
            switched = normalize(switch_layout(u.normalized))
            st = tokens(switched)
            if st and sum(t in self.vocab_set or t in self.synonyms for t in st) > 0:
                u.normalized, u.layout_fixed, toks = switched, True, st
        # Синонимы: сначала фразы из двух слов, затем отдельные слова.
        used = set()
        for i in range(len(toks) - 1):
            phrase = f"{toks[i]} {toks[i + 1]}"
            if phrase in self.synonyms:
                u.expansions += self.synonyms[phrase]
                used |= {i, i + 1}
        if u.normalized in self.synonyms:
            u.expansions += self.synonyms[u.normalized]
        for i, t in enumerate(toks):
            if i not in used and t in self.synonyms:
                u.expansions += self.synonyms[t]
        # Опечатки и кириллица вместо латиницы: «мдаемон» -> mdaemon, «линукс» -> linux.
        for t in toks:
            if t in self.vocab_set or t in self.synonyms or t.isdigit() or len(t) < 4:
                continue
            cands = [t, translit(t)] if has_cyr(t) else [t]
            best = None
            for c in cands:
                if c in self.vocab_set:
                    best = (c, 100)
                    break
                m = process.extractOne(c, self.vocab_keys, scorer=fuzz.ratio, score_cutoff=80)
                if m and (best is None or m[1] > best[1]):
                    best = (m[0], m[1])
            if best and best[0] != t:
                u.corrections[t] = best[0]
        u.expansions = list(dict.fromkeys(u.expansions))
        # Вендоры, упомянутые в запросе.
        exp = u.expanded
        for vn, v in self.ix.vendor_names.items():
            if len(vn) >= 3 and re.search(rf"(?<![a-zа-я0-9]){re.escape(vn)}(?![a-zа-я0-9])", exp):
                u.vendors.append(v)
        u.vendors = list(dict.fromkeys(u.vendors))
        self._detect_intent(u)
        return u

    def _detect_intent(self, u: Understanding) -> None:
        words = set(tokens(u.expanded))
        hw = words & HARDWARE_WORDS
        sw = words & SOFTWARE_WORDS
        if hw and not sw:
            u.intent = "hardware"
            u.intent_reason = f"запрос про оборудование: «{', '.join(sorted(hw))}»"
        elif sw and hw and hw <= AMBIGUOUS:
            u.intent = "software"
            u.intent_reason = f"«{', '.join(sorted(hw))}» в контексте ПО: «{', '.join(sorted(sw))}»"
        elif sw and not hw:
            u.intent = "software"
            u.intent_reason = "запрос про программное обеспечение"

    # ---------- отбор и ранжирование ----------
    def _retrieve(self, u: Understanding, k: int = 300) -> tuple[np.ndarray, np.ndarray, float]:
        q_stems = stems(u.expanded)
        bm = self.ix.bm25.scores(q_stems)
        qv = embed([f"query: {u.expanded}"])[0]
        sem = self.ix.emb @ qv
        bm_rank = np.argsort(-bm)[:k]
        sem_rank = np.argsort(-sem)[:k]
        score = np.zeros(len(self.p), dtype=np.float32)
        for r, i in enumerate(bm_rank):
            if bm[i] > 0:
                score[i] += 1.0 / (RRF_K + r)
        for r, i in enumerate(sem_rank):
            score[i] += 1.0 / (RRF_K + r)
        # Вендор из запроса и совпадение названия.
        if u.vendors:
            vset = {normalize(v) for v in u.vendors}
            score += np.isin(self._vendor_norm, list(vset)).astype(np.float32) * 0.01
        qtok = [t for t in tokens(" ".join([u.normalized, *u.corrections.values(), *u.expansions])) if len(t) > 1]
        q_cat = {s for s in q_stems if len(s) >= 4}
        cand = np.nonzero(score)[0]
        lexical = np.zeros(len(self.p), dtype=bool)
        for i in cand:
            title = self._titles[i]
            hits = sum(1 for t in qtok if t in title)
            if hits:
                score[i] += 0.006 * min(hits, 3)
                lexical[i] = True
                # Название начинается со слова запроса: «Сервер INFERIT…» важнее «Радиатор для сервера».
                if any(title.startswith(s) for s in q_cat):
                    score[i] += 0.006
                # Аксессуар к искомому товару («Сумка для ноутбука») ниже самого товара.
                elif any(f"для {s}" in title for s in q_cat):
                    score[i] -= 0.008
            # Запрос называет категорию («сервер», «антивирус»): товары этой категории выше.
            if q_cat & self.ix.category_stems[i]:
                score[i] += 0.008
        # Намерение: не показываем ПО на запрос про оборудование и наоборот.
        if u.intent == "hardware":
            score *= np.where(self.is_hw, 1.0, 0.25)
        elif u.intent == "software":
            score *= np.where(self.is_hw, 0.25, 1.0)
        else:
            # Намерение не названо: берём его из лучших совпадений по названию («max patrol» -> ПО, а не мыши Max).
            top_lex = [i for i in np.argsort(-score)[:10] if lexical[i]][:3]
            if top_lex and len({bool(self.is_hw[i]) for i in top_lex}) == 1:
                hw = bool(self.is_hw[top_lex[0]])
                score *= np.where(self.is_hw == hw, 1.0, 0.5)
        # Добор до минимума: при нехватке точных совпадений выше идут товары той же категории, что и лучший.
        if lexical.sum() < MIN_RESULTS * 2 and score.max() > 0:
            anchor = int(np.argmax(score))
            same_cat = (self.p["category_id"].to_numpy() == self.p["category_id"].iat[anchor]) & ~lexical
            score += same_cat.astype(np.float32) * 0.004 * (score > 0)
        return score, sem, float(bm.max()) if len(bm) else 0.0

    def search(self, query: str, limit: int = 12, use_llm: bool = True) -> dict:
        t0 = time.perf_counter()
        u = self.understand(query)
        score, sem, bm_max = self._retrieve(u)
        order = np.argsort(-score)
        top = [int(i) for i in order[: max(limit, MIN_RESULTS)] if score[i] > 0]
        confidence = self._confidence(u, top, sem, bm_max)
        llm_used = False
        if confidence < 0.5 and use_llm and self.llm is not None:
            rewritten = self.llm.rewrite(query)
            if rewritten and normalize(rewritten) != u.normalized:
                u2 = self.understand(rewritten)
                u2.raw, u2.rewritten_by_llm = query, rewritten
                score2, sem2, bm2 = self._retrieve(u2)
                order2 = np.argsort(-score2)
                top2 = [int(i) for i in order2[: max(limit, MIN_RESULTS)] if score2[i] > 0]
                c2 = self._confidence(u2, top2, sem2, bm2)
                if c2 >= confidence + 0.1:
                    u, top, confidence, sem = u2, top2, c2, sem2
                llm_used = True
        # Гарантия минимума: добираем ближайшие по смыслу товары.
        if len(top) < MIN_RESULTS:
            for i in np.argsort(-sem):
                if int(i) not in top:
                    top.append(int(i))
                if len(top) >= MIN_RESULTS:
                    break
        items = [self._card(i, rank) for rank, i in enumerate(top[:limit])]
        status = "ok" if confidence >= 0.5 else ("weak" if confidence >= 0.3 else "no_match")
        result = {
            "query": query,
            "understanding": {**asdict(u), "expanded": u.expanded},
            "status": status,
            "confidence": round(confidence, 3),
            "llm_used": llm_used,
            "items": items,
            "bundles": self.recommend(top[0], exclude=set(top[:limit])) if top else [],
            "alternatives": self.alternatives(top[0], exclude=set(top[:limit])) if top else [],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        return result

    def _confidence(self, u: Understanding, top: list[int], sem: np.ndarray, bm_max: float) -> float:
        """0..1: насколько выдача отвечает на запрос. Низкая уверенность -> LLM и метка в аналитике."""
        if not top:
            return 0.0
        # Значимые слова запроса: без служебных и общих («программа», «для», «работы»).
        groups = [[stem(t) for t in tokens(w) if t not in STOP and stem(t) not in GENERIC and len(t) > 1]
                  for w in [u.normalized]]
        alt = {stem(t) for w in [*u.corrections.values(), *u.expansions] for t in tokens(w)}
        words = [w for w in groups[0]]
        if not words and not alt:
            return float(np.clip((sem[top[0]] - 0.78) / 0.1, 0, 1))
        hay = " ".join([self._titles[top[0]], self._vendor_norm[top[0]], normalize(self.p["category"].iat[top[0]])])
        hay_stems = set(stems(hay)) | set(tokens(hay))
        matched = sum(1 for w in words if w in hay_stems or w in hay) + (1 if alt & hay_stems else 0)
        lexical = min(1.0, matched / max(1, len(words)))
        semantic = float(np.clip((sem[top[0]] - 0.78) / 0.1, 0, 1))
        return 0.6 * lexical + 0.4 * semantic

    def _card(self, i: int, rank: int | None = None) -> dict:
        r = self.p.iloc[i]
        badges = []
        if r["max_discount"] > 0:
            badges.append({"type": "promo", "text": f"Акция −{round(r['max_discount'] * 100)}%"})
        if r["n_offers"] > 1:
            badges.append({"type": "variants", "text": f"{int(r['n_offers'])} вариантов лицензии"})
        return {
            "product_id": int(r["product_id"]),
            "title": r["title"],
            "vendor": r["vendor"],
            "category": r["category_path"],
            "kind": "оборудование" if r["product_type"] == "электроника" else "ПО",
            "price_from": r["min_price"],
            "url": r["url"],
            "picture": r["picture"],
            "badges": badges,
        }

    # ---------- допродажа ----------
    def _quick(self, query: str, n: int = 6) -> list[int]:
        """Поиск для блоков допродажи: запросы фиксированы, результаты кешируются."""
        if query not in self._quick_cache:
            u = self.understand(query)
            score, _, _ = self._retrieve(u, k=100)
            self._quick_cache[query] = [int(i) for i in np.argsort(-score)[:n] if score[i] > 0]
        return self._quick_cache[query]

    def warmup(self) -> None:
        for blocks in [*COMPLEMENTS.values(), DEFAULT_COMPLEMENTS]:
            for q, _ in blocks:
                self._quick(q)

    def recommend(self, anchor: int, exclude: set[int], per_block: int = 2) -> list[dict]:
        r = self.p.iloc[anchor]
        blocks = []
        # Экосистема вендора: другие линейки того же производителя.
        same = self.p[(self.p["vendor"] == r["vendor"]) & (self.p["title"] != r["title"])]
        same = same[~same["product_id"].isin(exclude)].drop_duplicates("category").head(per_block + 1)
        if len(same):
            blocks.append({"title": f"Другие решения {r['vendor']}", "reason": "экосистема вендора",
                           "items": [self._card(int(i)) for i in same.index]})
        for q, label in COMPLEMENTS.get(r["root"], DEFAULT_COMPLEMENTS):
            ids = [i for i in self._quick(q) if i not in exclude and self.p.iloc[i]["vendor"] != r["vendor"]][:per_block]
            if ids:
                blocks.append({"title": label, "reason": f"часто нужны вместе с «{r['root']}»",
                               "items": [self._card(i) for i in ids]})
                exclude |= set(ids)
        return blocks[:4]

    def alternatives(self, anchor: int, exclude: set[int], n: int = 4) -> list[dict]:
        """Аналоги: та же категория, другой производитель."""
        r = self.p.iloc[anchor]
        alt = self.p[(self.p["category_id"] == r["category_id"]) & (self.p["vendor"] != r["vendor"])]
        alt = alt[~alt["product_id"].isin(exclude)].drop_duplicates("vendor").sort_values("min_price").head(n)
        return [self._card(int(i)) for i in alt.index]

    # ---------- подсказки при вводе ----------
    def suggest(self, prefix: str, n: int = 6) -> dict:
        t0 = time.perf_counter()
        p = normalize(prefix)
        if len(p) < 2:
            return {"prefix": prefix, "completions": [], "products": [], "latency_ms": 0}
        alt = normalize(switch_layout(p))
        completions = []
        for cand in (p, alt):
            hits = [t for t in self._titles if t.startswith(cand)]
            completions += hits[:n]
        u = self.understand(prefix)
        score, _, _ = self._retrieve(u, k=80)
        ids = [int(i) for i in np.argsort(-score)[:n] if score[i] > 0]
        fix = " ".join(u.corrections.values()) or (u.normalized if u.layout_fixed else "")
        return {
            "prefix": prefix,
            "did_you_mean": fix,
            "completions": list(dict.fromkeys(completions))[:n],
            "products": [self._card(i) for i in ids],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
