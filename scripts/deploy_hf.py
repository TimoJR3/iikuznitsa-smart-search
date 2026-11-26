"""Выкладывает стенд в Hugging Face Space: python scripts/deploy_hf.py <user>/<space>

Перед запуском: `huggingface-cli login` с токеном на запись, в настройках Space — секреты
FEED_FOLDER_URL и GIGACHAT_CREDENTIALS. Space пересобирается автоматически после загрузки.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
FILES = ["smartsearch", "app", "scripts", "eval", "requirements.txt", "data/synonyms.json", "data/vendor_facts.json", "data/alternatives.json"]


def main() -> None:
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit("Укажите Space: python scripts/deploy_hf.py <user>/<space>")
    repo_id = sys.argv[1]
    api = HfApi()
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for f in FILES:
            src, dst = ROOT / f, out / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(src, dst)
        shutil.copy2(ROOT / "deploy/hf/Dockerfile", out / "Dockerfile")
        shutil.copy2(ROOT / "deploy/hf/README.md", out / "README.md")
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=out,
                          commit_message="Обновление стенда из GitHub-репозитория")
    print(f"Готово: https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    main()
