"""GigaChat: переписывает запрос, который гибридный поиск понял неуверенно. Ответы кешируются, расход пишется в журнал."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

PROMPT = (
    "Ты помогаешь поиску интернет-магазина store.softline.ru: программное обеспечение и компьютерное оборудование "
    "для компаний. Перепиши запрос покупателя в 2–6 слов, как товар назван в каталоге: категория товара и, если "
    "уместно, 2–3 известных бренда из этой категории. Исправь опечатки, жаргон и раскладку. Ответь одной строкой, "
    "только слова через пробел, без пояснений. Если запрос бессмысленный или не про ПО и оборудование, ответь: НЕТ"
    "\nЗапрос: {query}"
)


class GigaChatRewriter:
    def __init__(self, credentials: str, ca_bundle: str | None, model: str = "GigaChat-2",
                 cache_path: Path | None = None, usage_log: Path | None = None, timeout: float = 8.0) -> None:
        from gigachat import GigaChat

        self.client = GigaChat(credentials=credentials, scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                               model=model, ca_bundle_file=ca_bundle, timeout=timeout)
        self.model = model
        self.cache_path = cache_path
        self.usage_log = usage_log
        self.cache: dict[str, str] = {}
        if cache_path and cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, data_dir: Path) -> "GigaChatRewriter | None":
        cred = os.getenv("GIGACHAT_CREDENTIALS")
        if not cred:
            return None
        return cls(cred, os.getenv("GIGACHAT_CA_BUNDLE"), os.getenv("GIGACHAT_MODEL", "GigaChat-2"),
                   cache_path=data_dir / "llm_cache.json", usage_log=data_dir / "llm_usage.jsonl")

    def rewrite(self, query: str) -> str | None:
        key = query.strip().lower()
        if key in self.cache:
            return self.cache[key]
        t = time.perf_counter()
        try:
            r = self.client.chat(PROMPT.format(query=query.strip()[:200]))
        except Exception as e:  # сеть, лимиты, ключ: поиск продолжает работать без LLM
            self._log({"query": query, "error": type(e).__name__})
            return None
        lines = [ln.strip(" .\"«»*-") for ln in r.choices[0].message.content.splitlines() if ln.strip(" .\"«»*-")]
        text = lines[0][:120] if lines else ""
        if text.upper().startswith("НЕТ"):
            text = ""
        self._log({"query": query, "rewrite": text, "model": self.model,
                   "prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens,
                   "latency_ms": round((time.perf_counter() - t) * 1000)})
        with self._lock:
            self.cache[key] = text
            if self.cache_path:
                self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return text

    def _log(self, rec: dict) -> None:
        if self.usage_log:
            rec["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
            with self._lock, self.usage_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
