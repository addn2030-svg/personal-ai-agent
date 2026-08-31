FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-connectors.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "-lc", "if [ \"${AI_OS_DISABLE_TELEGRAM:-0}\" = \"1\" ]; then exec python3 -u connectors/commerce_staging_server.py; else exec python3 -u connectors/telegram_webhook_runtime.py; fi"]
