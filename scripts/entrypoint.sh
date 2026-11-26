#!/bin/sh
# Индекс собирается один раз и хранится в томе data/: перезапуск контейнера не пересобирает его.
set -e
if [ ! -f data/index/products.parquet ]; then
  python scripts/build_index.py --feed data/raw/Mindbox.yml.gz.xml --out data/index
  python scripts/replay_queries.py || true
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
