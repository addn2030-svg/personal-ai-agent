"""Shared OpenAI-compatible client for the configured OmniRoute gateway."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

OMNIROUTE_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "").strip().rstrip("/")
OMNIROUTE_API_KEY = os.environ.get("OMNIROUTE_API_KEY", "").strip()
OMNIROUTE_MODEL = os.environ.get("OMNIROUTE_MODEL", "").strip()
OMNIROUTE_TIMEOUT_SECONDS = float(os.environ.get("OMNIROUTE_TIMEOUT_SECONDS", "90"))


def configured() -> bool:
    return bool(OMNIROUTE_BASE_URL and OMNIROUTE_API_KEY and OMNIROUTE_MODEL)


def _api_root() -> str:
    if not OMNIROUTE_BASE_URL:
        raise RuntimeError("OMNIROUTE_BASE_URL is not configured")
    parsed = urlsplit(OMNIROUTE_BASE_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("OMNIROUTE_BASE_URL must be an absolute HTTP(S) URL")
    return OMNIROUTE_BASE_URL if parsed.path.rstrip("/").endswith("/v1") else OMNIROUTE_BASE_URL + "/v1"


def _safe_error(exc: Exception) -> str:
    value = str(exc)
    if OMNIROUTE_API_KEY:
        value = value.replace(OMNIROUTE_API_KEY, "[REDACTED]")
    return value[:600]


def request_json(path: str, *, payload: dict | None = None, timeout: float | None = None) -> tuple[dict, int]:
    if not OMNIROUTE_API_KEY:
        raise RuntimeError("OMNIROUTE_API_KEY is not configured")
    url = _api_root() + path
    headers = {
        "Authorization": f"Bearer {OMNIROUTE_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "Abdulrahman-AI-OS",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout or OMNIROUTE_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:800]
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"OmniRoute HTTP {exc.code}: {_safe_error(RuntimeError(detail))}") from exc
    except Exception as exc:
        raise RuntimeError(f"OmniRoute request failed: {_safe_error(exc)}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("OmniRoute returned an invalid JSON object")
    return result, int((time.monotonic() - started) * 1000)


def chat_completion(
    *, model: str, messages: list[dict], max_tokens: int = 1200,
    temperature: float = 0.2, response_format: dict | None = None,
) -> tuple[str, dict, int, str]:
    if not model or not str(model).strip():
        raise RuntimeError("OMNIROUTE_MODEL (or an explicit OmniRoute model ID) is required")
    body = {
        "model": str(model).strip(),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format:
        body["response_format"] = response_format
    result, latency_ms = request_json("/chat/completions", payload=body)
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("OmniRoute returned no choices")
    content = ((choices[0].get("message") or {}).get("content"))
    if isinstance(content, list):
        answer = "\n".join(
            str(part.get("text", "")) for part in content
            if isinstance(part, dict) and part.get("text")
        ).strip()
    else:
        answer = str(content or "").strip()
    if not answer:
        raise RuntimeError("OmniRoute returned an empty response")
    raw_usage = result.get("usage") or {}
    usage = {
        "inputTokens": raw_usage.get("prompt_tokens", raw_usage.get("input_tokens", "")),
        "outputTokens": raw_usage.get("completion_tokens", raw_usage.get("output_tokens", "")),
    }
    return answer, usage, latency_ms, str(result.get("model") or model)


def list_models() -> list[str]:
    result, _ = request_json("/models", timeout=20)
    return [str(row["id"]) for row in result.get("data", []) if isinstance(row, dict) and row.get("id")]


def probe() -> dict:
    if not configured():
        missing = [
            name for name, value in (
                ("OMNIROUTE_BASE_URL", OMNIROUTE_BASE_URL),
                ("OMNIROUTE_API_KEY", OMNIROUTE_API_KEY),
                ("OMNIROUTE_MODEL", OMNIROUTE_MODEL),
            ) if not value
        ]
        return {"configured": False, "ok": False, "missing": missing}
    try:
        answer, usage, latency_ms, model = chat_completion(
            model=OMNIROUTE_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=16,
            temperature=0,
        )
        return {"configured": True, "ok": bool(answer), "model": model, "latency_ms": latency_ms, "usage": usage}
    except Exception as exc:
        return {"configured": True, "ok": False, "model": OMNIROUTE_MODEL, "detail": _safe_error(exc)}
