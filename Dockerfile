FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt requirements-connectors.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a module, not as a script: `python3 connectors/...` puts /app/connectors on
# sys.path instead of /app, so `from connectors import ...` fails and the deploy
# crash-loops. `python3 -m` adds the working directory (/app) instead.
CMD ["python3", "-u", "-m", "connectors.telegram_webhook_runtime_memory"]