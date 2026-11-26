# Образ для Hugging Face Spaces (Docker SDK). Данные задачи скачиваются при сборке по ссылке из секрета
# FEED_FOLDER_URL, индекс и модель эмбеддингов попадают в образ, поэтому старт занимает секунды.
FROM python:3.11-slim
ENV OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1 HF_HOME=/app/data/hf
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates openssl && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer -o /tmp/ru.cer \
 && (openssl x509 -in /tmp/ru.cer -out /usr/local/share/ca-certificates/russian_trusted_root_ca.crt || openssl x509 -inform DER -in /tmp/ru.cer -out /usr/local/share/ca-certificates/russian_trusted_root_ca.crt) \
 && update-ca-certificates
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY smartsearch smartsearch
COPY app app
COPY scripts scripts
COPY eval eval
COPY data/synonyms.json data/vendor_facts.json data/alternatives.json data/
RUN --mount=type=secret,id=FEED_FOLDER_URL,mode=0444,required=true \
    gdown --folder "$(cat /run/secrets/FEED_FOLDER_URL)" -O data/raw \
 && python scripts/build_index.py --feed data/raw/Mindbox.yml.gz.xml --out data/index \
 && python scripts/replay_queries.py \
 && rm -f data/raw/Mindbox.yml.gz.xml \
 && chown -R user:user /app/data
USER user
ENV GIGACHAT_CA_BUNDLE=/usr/local/share/ca-certificates/russian_trusted_root_ca.crt
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
