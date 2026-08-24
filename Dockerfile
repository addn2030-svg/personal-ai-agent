FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-connectors.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "-u", "connectors/telegram_webhook.py"]
