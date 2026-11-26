FROM python:3.11-slim
ENV OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 HF_HOME=/app/data/hf PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates openssl && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer -o /tmp/ru.cer \
 && (openssl x509 -in /tmp/ru.cer -out /usr/local/share/ca-certificates/russian_trusted_root_ca.crt || openssl x509 -inform DER -in /tmp/ru.cer -out /usr/local/share/ca-certificates/russian_trusted_root_ca.crt) \
 && update-ca-certificates
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY smartsearch smartsearch
COPY app app
COPY scripts scripts
COPY eval eval
COPY data/synonyms.json data/synonyms.json
ENV GIGACHAT_CA_BUNDLE=/usr/local/share/ca-certificates/russian_trusted_root_ca.crt
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s CMD curl -fs localhost:8000/health || exit 1
CMD ["sh", "scripts/entrypoint.sh"]
