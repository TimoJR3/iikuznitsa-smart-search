# Образ для Cloud.ru Evolution Container Apps. Индекс собирается заранее (python scripts/build_index.py),
# в образ попадают индекс, модель эмбеддингов и выборка запросов магазина для вкладки аналитики.
# Сборка из корня репозитория:
#   docker build --platform linux/amd64 -f deploy/cloudru/Dockerfile -t smart-search:v1 .
FROM python:3.11-slim
ENV OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1 HF_HOME=/app/data/hf PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates openssl && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer -o /tmp/ru.cer \
 && (openssl x509 -in /tmp/ru.cer -out /usr/local/share/ca-certificates/russian_trusted_root_ca.crt || openssl x509 -inform DER -in /tmp/ru.cer -out /usr/local/share/ca-certificates/russian_trusted_root_ca.crt) \
 && update-ca-certificates
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"
COPY smartsearch smartsearch
COPY app app
COPY scripts scripts
COPY eval eval
COPY data/synonyms.json data/synonyms.json
COPY data/index data/index
COPY ["data/raw/Выборка поисковых запросов.xlsx", "data/raw/"]
RUN python scripts/replay_queries.py > /dev/null
ENV GIGACHAT_CA_BUNDLE=/usr/local/share/ca-certificates/russian_trusted_root_ca.crt
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fs localhost:${PORT}/health || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
