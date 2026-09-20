# -*- coding: utf-8 -*-
"""Supabase connector — REST (PostgREST) client for Abdulrahman AI OS.

يقرأ ويكتب في مشروع Supabase عبر واجهة REST الرسمية، بلا أي اعتماديات خارجية
(`urllib` فقط، كما في بقية الموصلات). لا تحتاج هذه الوحدة إلى `supabase-py`.

المتغيرات (تُضبط في Railway → Variables أو في `.env` محليًا — لا في Git ولا في محادثة):

| المتغير | الغرض |
|---|---|
| `SUPABASE_URL` | رابط المشروع: `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | مفتاح publishable/anon — **للقراءة فقط** عبر سياسات RLS |
| `SUPABASE_SERVICE_ROLE_KEY` | مفتاح secret/service_role — **يكتب**، يبقى على الخادم فقط |
| `SUPABASE_WRITE_ENABLED` | `1` لتفعيل أي كتابة (مغلق افتراضيًا) |
| `SUPABASE_SCHEMA` | المخطط الافتراضي `public` |

أسماء بديلة مقبولة: `SUPABASE_PUBLISHABLE_KEY` / `SUPABASE_KEY` للمفتاح العام،
و`SUPABASE_SECRET_KEY` / `SUPABASE_SERVICE_KEY` للمفتاح السري.

قواعد السلامة المطبَّقة في الكود:
1. لا تُطبع المفاتيح أبدًا — كل رسالة خطأ تمر بـ`redact()` قبل العرض.
2. الكتابة ممنوعة ما لم يكن `SUPABASE_WRITE_ENABLED=1` **و**المفتاح سريًا؛
   مفتاح anon/publishable لا يكتب إطلاقًا حتى لو فُعّل المتغير.
3. رابط لوحة التحكم (`supabase.com/dashboard/...`) يُرفض بوضوح — القيمة الصحيحة
   هي رابط المشروع `https://<ref>.supabase.co`.
4. لا يتصل الموصل بالشبكة عند التحميل؛ الاتصال فقط عند طلب صريح.

أمثلة:
  python3 -m connectors.supabase_client --check     # فحص الإعداد (بلا شبكة)
  python3 -m connectors.supabase_client --live      # فحص حي عبر الشبكة
  python3 -m connectors.supabase_client --sql       # طباعة SQL المطلوب تشغيله
"""
from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:  # allow `python3 connectors/supabase_client.py`
    sys.path.insert(0, BASE)

URL_VARS = ("SUPABASE_URL",)
ANON_KEY_VARS = ("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY")
SECRET_KEY_VARS = ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_KEY")

PUBLISHABLE_PREFIX = "sb_publishable_"
SECRET_PREFIX = "sb_secret_"

DEFAULT_TIMEOUT = float(os.environ.get("SUPABASE_TIMEOUT_SECONDS", "20"))
DEFAULT_SCHEMA = os.environ.get("SUPABASE_SCHEMA", "").strip() or "public"

# PostgREST / GoTrue error codes worth explaining instead of echoing raw.
_ERROR_HINTS = {
    "42P01": "الجدول غير موجود — شغّل SQL الإعداد: python3 -m connectors.supabase_client --sql",
    "PGRST202": "الدالة غير موجودة في المخطط المطلوب",
    "PGRST205": "الجدول غير مكشوف لواجهة REST — تحقق من المخطط (SUPABASE_SCHEMA)",
    "PGRST301": "المفتاح غير مقبول لهذه العملية (JWT)",
    "42501": "RLS منعت العملية — استخدم المفتاح السري للكتابة، أو أضف سياسة مناسبة",
}


class SupabaseError(RuntimeError):
    """خطأ موصل Supabase — رسالته منقّاة ولا تحتوي أي مفتاح."""

    def __init__(self, message: str, *, status: int | None = None, code: str = "",
                 detail: str = "", hint: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail
        self.hint = hint

    @property
    def is_transient(self) -> bool:
        """أخطاء شبكة/خادم يمكن إعادة المحاولة عليها لاحقًا."""
        return self.status is None or self.status in (429, 500, 502, 503, 504)

    def as_dict(self) -> dict:
        return {
            "error": str(self), "status": self.status, "code": self.code,
            "detail": self.detail, "hint": self.hint,
        }


# ----------------------------------------------------------------- key helpers
def redact(text: str, *secrets: str) -> str:
    """إزالة أي مفتاح من نص قبل عرضه — يمنع تسرّب المفاتيح في السجلات."""
    out = str(text or "")
    for secret in secrets:
        secret = (secret or "").strip()
        if secret and len(secret) >= 8:
            out = out.replace(secret, "***")
    return out


def key_kind(key: str) -> str:
    """تصنيف المفتاح: publishable | secret | anon | service_role | unknown.

    يفهم مفاتيح النظام الجديد (`sb_publishable_` / `sb_secret_`) والقديمة (JWT
    يحمل `role` = anon أو service_role).
    """
    key = (key or "").strip()
    if not key:
        return "unknown"
    if key.startswith(PUBLISHABLE_PREFIX):
        return "publishable"
    if key.startswith(SECRET_PREFIX):
        return "secret"
    parts = key.split(".")
    if len(parts) >= 2:
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        except Exception:  # noqa: BLE001 - أي فشل فك ترميز = مفتاح غير معروف
            return "unknown"
        role = str(claims.get("role") or "").strip()
        if role in ("anon", "authenticated"):
            return "anon"
        if role == "service_role":
            return "service_role"
    return "unknown"


def is_secret_key(kind: str) -> bool:
    return kind in ("secret", "service_role")


def validate_url(url: str) -> str:
    """يعيد الرابط مُنظَّفًا أو يرفع SupabaseError يشرح الخطأ الشائع."""
    value = (url or "").strip().rstrip("/")
    if not value:
        raise SupabaseError("SUPABASE_URL غير مضبوط — انسخ Project URL من Settings → API Keys")
    lowered = value.lower()
    if "supabase.com/dashboard" in lowered or "/project/" in lowered:
        raise SupabaseError(
            "SUPABASE_URL يبدو رابط لوحة التحكم، وليس رابط المشروع. "
            "الصحيح مثل: https://abcdefgh.supabase.co"
        )
    if lowered.startswith("https://"):
        scheme = "https://"
    elif lowered.startswith("http://"):
        # نص plain يسمح فقط للاستضافة الذاتية/الاختبار المحلي — والمفتاح يبقى في الشبكة مكشوفًا.
        scheme = "http://"
    else:
        raise SupabaseError("SUPABASE_URL يجب أن يبدأ بـ https:// (مثال: https://abcdefgh.supabase.co)")
    host = lowered[len(scheme):].split("/")[0].split(":")[0]
    if not host or "." not in host and host not in ("localhost",):
        raise SupabaseError("SUPABASE_URL لا يحتوي اسم مضيف صالح (مثال: https://abcdefgh.supabase.co)")
    if scheme == "http://" and host not in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"):
        raise SupabaseError(
            "http:// غير مشفّر مسموح للمضيف المحلي فقط (اختبار/استضافة ذاتية). "
            "للمشروع السحابي استخدم https://<ref>.supabase.co"
        )
    return value


# -------------------------------------------------------------------- config
@dataclass
class SupabaseConfig:
    url: str = ""
    anon_key: str = ""
    secret_key: str = ""
    write_enabled: bool = False
    schema: str = DEFAULT_SCHEMA
    sources: dict = field(default_factory=dict)  # env var name → which slot it filled

    # -- capabilities -----------------------------------------------------
    @property
    def key(self) -> str:
        """المفتاح المستخدم فعليًا: السري إن وُجد، وإلا العام."""
        return self.secret_key or self.anon_key

    @property
    def key_kind(self) -> str:
        secret_kind, anon_kind = key_kind(self.secret_key), key_kind(self.anon_key)
        if self.secret_key and is_secret_key(secret_kind):
            return secret_kind
        if self.secret_key:
            # قيمة غريبة في خانة السرّية: لا نمنحها صلاحية كتابة.
            return secret_kind if self.secret_key != self.anon_key else anon_kind
        return anon_kind

    @property
    def all_keys(self) -> tuple:
        """كل المفاتيح المضبوطة — تُستخدم لتنقية أي نص قبل عرضه."""
        return tuple(k for k in (self.secret_key, self.anon_key) if k)

    @property
    def url_error(self) -> str:
        """رسالة توضح لماذا الرابط غير صالح (فارغ = صالح أو غير مضبوط أصلًا)."""
        if not (self.url or "").strip():
            return ""
        try:
            validate_url(self.url)
            return ""
        except SupabaseError as exc:
            return str(exc)

    @property
    def problem(self) -> str:
        """أول عائق يمنع الاستخدام — رسالة واحدة قابلة للتنفيذ."""
        if self.url_error:
            return self.url_error
        if not self.url:
            return "SUPABASE_URL غير مضبوط — انسخ Project URL من Settings → API Keys"
        if not self.key:
            return "لا مفتاح: اضبط SUPABASE_ANON_KEY أو SUPABASE_SERVICE_ROLE_KEY"
        return ""

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key) and not self.url_error

    @property
    def can_read(self) -> bool:
        return self.configured

    @property
    def can_write(self) -> bool:
        """الكتابة تحتاج مفتاحًا سريًا + تفعيلًا صريحًا."""
        return bool(self.configured and self.write_enabled and is_secret_key(key_kind(self.secret_key)))

    def summary(self) -> dict:
        """وصف آمن (بلا قيم) — يُستخدم في الفحوص والتشخيص."""
        kind = self.key_kind
        if not self.url and not self.key:
            status, detail = "missing", "SUPABASE_URL والمفتاح غير مضبوطين"
        elif not self.url:
            status, detail = "partial", "SUPABASE_URL غير مضبوط"
        elif self.url_error:
            status, detail = "invalid", self.url_error
        elif not self.key:
            status, detail = "partial", "لا مفتاح: اضبط SUPABASE_ANON_KEY أو SUPABASE_SERVICE_ROLE_KEY"
        elif kind == "unknown":
            status, detail = "invalid", "المفتاح غير معروف الشكل (توقع sb_publishable_… أو sb_secret_… أو JWT)"
        elif is_secret_key(kind):
            mode = "قراءة وكتابة (مفتاح سري — يبقى على الخادم فقط)" if self.write_enabled else "قراءة (الكتابة مغلقة: SUPABASE_WRITE_ENABLED≠1)"
            status, detail = "ok", f"مفتاح من نوع {kind} — {mode}"
        else:
            status, detail = "ok", (
                f"مفتاح من نوع {kind} — قراءة فقط عبر سياسات RLS "
                "(الكتابة تحتاج SUPABASE_SERVICE_ROLE_KEY + SUPABASE_WRITE_ENABLED=1)"
            )
        return {
            "configured": self.configured, "status": status,
            "key_kind": kind, "url_host": _host(self.url), "schema": self.schema,
            "can_read": self.can_read, "can_write": self.can_write,
            "write_flag": self.write_enabled, "detail": detail,
        }


def _host(url: str) -> str:
    return (url or "").split("://", 1)[-1].split("/")[0]


def load_config(env=None) -> SupabaseConfig:
    """يبني الإعداد من البيئة (ويحمّل `.env` إن وُجد، دون تجاوز متغيرات حقيقية)."""
    if env is None:
        try:
            from engine.env_file import load_env
            load_env()
        except Exception:  # noqa: BLE001 - غياب محمّل .env لا يعطّل الموصل
            pass
    get = env or (lambda name: os.environ.get(name, ""))

    def first(names):
        for name in names:
            value = (get(name) or "").strip()
            if value:
                return name, value
        return "", ""

    url_name, url = first(URL_VARS)
    anon_name, anon = first(ANON_KEY_VARS)
    secret_name, secret = first(SECRET_KEY_VARS)
    # نفس القيمة في الخانتين ⇒ تُعامل كمفتاح عام (لا صلاحية كتابة تُمنح بالخطأ).
    sources = {k: v for k, v in (("url", url_name), ("anon", anon_name), ("secret", secret_name)) if v}
    return SupabaseConfig(
        url=url, anon_key=anon, secret_key=secret,
        write_enabled=(get("SUPABASE_WRITE_ENABLED") or "").strip() in ("1", "true", "yes", "on"),
        schema=((get("SUPABASE_SCHEMA") or "").strip() or DEFAULT_SCHEMA),
        sources=sources,
    )


# -------------------------------------------------------------------- client
class SupabaseClient:
    """عميل REST بسيط: select / insert / upsert / delete / rpc / health."""

    def __init__(self, config: SupabaseConfig | None = None, *, timeout: float | None = None,
                 opener=None, env=None):
        self.cfg = config or load_config(env)
        self.timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        self._opener = opener or urlopen  # قابل للاستبدال في الاختبارات

    # -- plumbing ---------------------------------------------------------
    def _error_from_http(self, exc: HTTPError) -> SupabaseError:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        code = detail = hint = ""
        message = f"HTTP {exc.code}"
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                message = str(payload.get("message") or message)
                code = str(payload.get("code") or "")
                detail = str(payload.get("details") or "")
                hint = str(payload.get("hint") or "")
        except Exception:  # noqa: BLE001
            message = (body or message)[:300]
        # نجمع تلميحات الحالة (HTTP) والكود (PostgREST) معًا: كلاهما يوجّه المستخدم.
        hints: list[str] = []
        if exc.code == 401:
            hints.append("المفتاح غير صحيح أو من مشروع آخر — انسخه من Settings → API Keys")
        elif exc.code == 403:
            hints.append("RLS منعت العملية — استخدم المفتاح السري للكتابة أو أضف سياسة")
        elif exc.code == 404:
            hints.append("المسار أو الجدول غير موجود — للجدول: شغّل SQL الإعداد (--sql)")
        if code in _ERROR_HINTS:
            hints.append(_ERROR_HINTS[code])
        return SupabaseError(
            redact(message, *self.cfg.all_keys), status=exc.code, code=code, detail=detail,
            hint=" · ".join(dict.fromkeys(h for h in hints if h)),
        )

    def request(self, method: str, path: str, *, params: dict | None = None, body=None,
                extra_headers: dict | None = None, absolute: bool = False,
                timeout: float | None = None) -> object:
        """تنفيذ طلب واحد. `path` نسبي (مثل `/rest/v1/notes`) أو مطلق مع absolute=True."""
        if not self.cfg.configured:
            raise SupabaseError(
                "Supabase غير مضبوط — اضبط SUPABASE_URL و SUPABASE_ANON_KEY (أو المفتاح السري). "
                "الرحلة الكاملة: docs/supabase-setup.md"
            )
        url = path if absolute else validate_url(self.cfg.url) + path
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")

        request = Request(url, data=data, method=method.upper())
        key = self.cfg.key
        request.add_header("apikey", key)
        request.add_header("Authorization", f"Bearer {key}")
        request.add_header("Accept", "application/json")
        if self.cfg.schema and self.cfg.schema != "public":
            request.add_header("Accept-Profile", self.cfg.schema)
            request.add_header("Content-Profile", self.cfg.schema)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (extra_headers or {}).items():
            request.add_header(name, value)

        try:
            with self._opener(request, timeout=self.timeout if timeout is None else timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except HTTPError as exc:
            raise self._error_from_http(exc) from None
        except URLError as exc:
            raise SupabaseError(
                redact(f"تعذر الوصول إلى Supabase: {getattr(exc, 'reason', exc)}", *self.cfg.all_keys),
                hint="تحقق من الشبكة ومن صحة SUPABASE_URL",
            ) from None
        except Exception as exc:  # noqa: BLE001
            raise SupabaseError(redact(f"فشل طلب Supabase: {exc}", *self.cfg.all_keys)) from None

        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[:2000]

    def _require_write(self) -> None:
        if not self.cfg.write_enabled:
            raise SupabaseError(
                "الكتابة في Supabase مغلقة. فعّلها صراحةً بـ SUPABASE_WRITE_ENABLED=1 "
                "بعد ضبط SUPABASE_SERVICE_ROLE_KEY (يبقى على الخادم فقط).",
                hint="هذه بوابة سلامة مقصودة — القراءة لا تحتاجها",
            )
        if not is_secret_key(key_kind(self.cfg.secret_key)):
            raise SupabaseError(
                "الكتابة تحتاج مفتاحًا سريًا (service_role/secret). مفتاح anon/publishable "
                "لا يكتب أبدًا من هذا الموصل.",
                hint="Railway → Variables → SUPABASE_SERVICE_ROLE_KEY، ولا تضع هذا المفتاح في أي واجهة متصفح",
            )

    # -- REST ops ---------------------------------------------------------
    def health(self) -> dict:
        """فحص حي خفيف: يقرأ جذر PostgREST (بلا قراءة أي صف بيانات)."""
        payload = self.request("GET", "/rest/v1/", extra_headers={"Accept": "application/openapi+json"})
        tables: list[str] = []
        if isinstance(payload, dict):
            paths = payload.get("paths") or {}
            tables = sorted({p.strip("/").split("/")[0] for p in paths if p.strip("/")})[:50]
        return {"host": _host(self.cfg.url), "schema": self.cfg.schema,
                "key_kind": self.cfg.key_kind, "tables": tables}

    def select(self, table: str, *, columns: str = "*", filters: dict | None = None,
               order: str = "", limit: int = 100, count_exact: bool = False) -> list:
        params = {"select": columns, "limit": str(int(limit))}
        if order:
            params["order"] = order
        for key, value in (filters or {}).items():
            params[key] = value
        headers = {"Prefer": "count=exact"} if count_exact else None
        return self.request("GET", f"/rest/v1/{quote(table)}", params=params, extra_headers=headers) or []

    def insert(self, table: str, rows, *, returning: bool = True) -> list:
        self._require_write()
        rows = [rows] if isinstance(rows, dict) else list(rows)
        headers = {"Prefer": "return=representation" if returning else "return=minimal"}
        result = self.request("POST", f"/rest/v1/{quote(table)}", body=rows, extra_headers=headers)
        return result if isinstance(result, list) else ([] if result is None else [result])

    def upsert(self, table: str, rows, *, on_conflict: str = "", returning: bool = True) -> list:
        self._require_write()
        rows = [rows] if isinstance(rows, dict) else list(rows)
        prefer = "resolution=merge-duplicates," + ("return=representation" if returning else "return=minimal")
        params = {"on_conflict": on_conflict} if on_conflict else None
        result = self.request("POST", f"/rest/v1/{quote(table)}", params=params, body=rows,
                              extra_headers={"Prefer": prefer})
        return result if isinstance(result, list) else ([] if result is None else [result])

    def update(self, table: str, values: dict, *, match: dict, returning: bool = True) -> list:
        self._require_write()
        params = dict(match or {})
        headers = {"Prefer": "return=representation" if returning else "return=minimal"}
        result = self.request("PATCH", f"/rest/v1/{quote(table)}", params=params, body=values,
                              extra_headers=headers)
        return result if isinstance(result, list) else ([] if result is None else [result])

    def delete(self, table: str, *, match: dict, returning: bool = True) -> list:
        self._require_write()
        if not match:
            raise SupabaseError("رفض الحذف: لا مرشّح (match) — الحذف الشامل غير مسموح من هذا الموصل")
        headers = {"Prefer": "return=representation" if returning else "return=minimal"}
        result = self.request("DELETE", f"/rest/v1/{quote(table)}", params=dict(match),
                              extra_headers=headers)
        return result if isinstance(result, list) else ([] if result is None else [result])

    def rpc(self, function: str, payload: dict | None = None) -> object:
        return self.request("POST", f"/rest/v1/rpc/{quote(function)}", body=payload or {})


# ------------------------------------------------------------------ sql setup
SETUP_SQL = """-- Abdulrahman AI OS — مخطط Supabase (شغّله في SQL Editor مرة واحدة)
-- الجدول يحتفظ بنسخ كاملة من state.json خارج الخادم (نسخ احتياطي متين).
create table if not exists public.state_snapshots (
  id            bigint generated by default as identity primary key,
  created_at    timestamptz not null default now(),
  schema        text        not null default 'state/1',
  state_version integer     not null default 0,
  reason        text        not null default 'manual',
  sha256        text        not null,
  byte_size     integer     not null,
  payload       jsonb       not null
);

create index if not exists state_snapshots_created_at_idx
  on public.state_snapshots (created_at desc);

-- RLS مفعّل وبلا أي سياسة: لا يقرأ ولا يكتب أحد بالمفتاح العام (anon/publishable).
-- المفتاح السري (service_role) يتجاوز RLS، وهو الوحيد المستخدم من الخادم.
alter table public.state_snapshots enable row level security;
revoke all on public.state_snapshots from anon, authenticated;

-- إن أردت لاحقًا لوحة قراءة بالمفتاح العام، أضف سياسة ضيّقة صريحة (مثال يبقى معطّلًا):
-- create policy "anon reads snapshot dates only" on public.state_snapshots
--   for select to anon using (false);
"""


def doctor(env=None) -> dict:
    """فحص حي يُستدعى من `connectors.connection_setup --live` (بلا طباعة أسرار)."""
    client = SupabaseClient(load_config(env))
    info = client.health()
    table = (os.environ.get("SUPABASE_STATE_TABLE", "") or "state_snapshots").strip()
    info["state_table"] = table
    rows = client.select(table, columns="id,created_at,sha256,byte_size", order="created_at.desc", limit=1)
    info["snapshots_visible"] = len(rows or [])
    info["latest_snapshot"] = (rows or [{}])[0].get("created_at") if rows else None
    return info


def render_check(env=None) -> str:
    cfg = load_config(env)
    summary = cfg.summary()
    icon = {"ok": "✅", "partial": "⚠️", "missing": "○", "invalid": "❌"}.get(summary["status"], "❓")
    lines = [f"{icon} Supabase — {summary['detail']}"]
    if summary["url_host"]:
        lines.append(f"  • المشروع: {summary['url_host']} · المخطط: {summary['schema']}")
    lines.append(f"  • قراءة: {'نعم' if summary['can_read'] else 'لا'} · كتابة: {'نعم' if summary['can_write'] else 'لا'}")
    if not summary["can_write"]:
        lines.append("  • للكتابة: SUPABASE_SERVICE_ROLE_KEY + SUPABASE_WRITE_ENABLED=1 (على الخادم فقط)")
    return "\n".join(lines)


def main(argv) -> int:
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if "--sql" in argv:
        print(SETUP_SQL)
        return 0
    if "--live" in argv:
        cfg = load_config()
        if not cfg.configured:
            print(render_check())
            return 2
        print(render_check())
        try:
            info = doctor()
        except SupabaseError as exc:
            print(f"❌ الفحص الحي فشل: {exc}")
            if exc.hint:
                print(f"   تلميح: {exc.hint}")
            return 2
        print(f"✅ اتصال ناجح — المضيف {info['host']} · جداول ظاهرة: {len(info['tables'])}")
        print(f"   جدول النسخ: {info['state_table']} · صفوف مقروءة: {info['snapshots_visible']}")
        if info.get("latest_snapshot"):
            print(f"   أحدث نسخة: {info['latest_snapshot']}")
        return 0
    if "--json" in argv:
        print(json.dumps(load_config().summary(), ensure_ascii=False, indent=2))
        return 0
    print(render_check())
    return 0 if load_config().configured else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
