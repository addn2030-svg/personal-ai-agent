# 🔗 Connection Guide — All Integrations (aligned with the code)

This is the executable version of the handwritten checklist. Every step below maps to
the exact environment variables the connectors read, and every item can be verified with
one command:

```bash
python3 -m connectors.connection_setup          # config checks (no network)
python3 -m connectors.connection_setup --live   # + live API probes
python3 -m connectors.connection_setup --guide calendar   # steps for one integration
```

## ⚠️ Security first
- **Never paste tokens into chat** — not here, not in Telegram, not in any "setup request".
  Secrets go into environment variables only:
  - **Railway (the deployed bot):** service → *Variables* → add each variable.
  - **Local machine:** shell environment / `.env` (`.env*` and `secrets/` are already gitignored).
- The same Google **service account** covers Sheets, Drive, Docs and Calendar — you create it once.
- GitHub token scopes needed: `repo` (+ `workflow` only if CI workflow pushes are required).

---

## 1️⃣ Telegram Bot — ✅ Active
Code: `connectors/telegram_live.py`, `connectors/telegram_bot.py`, webhook runtime.

| Variable | Required |
|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ |

No action needed. The `--live` probe calls `getMe` (read-only, never sends).

## 2️⃣ Google Sheets — ⚠️ verify env
Code: `connectors/sheet_intelligence.py` (read/search/update through the approval-safe layer).

1. console.cloud.google.com → New Project → **Abdulrahman AI OS**.
2. APIs & Services → enable **Google Sheets API** and **Google Drive API**.
3. Credentials → Create Credentials → **Service Account** → name `abdulrahman-agent` → download the JSON key.
4. Share your Sheet with the **service-account email** (Editor).

| Variable | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | the key JSON — inline, base64, double-encoded, or a `*.json` file path (all four are auto-detected by `connectors/google_credentials.py`) |
| `GOOGLE_SHEET_ID` | id between `/d/` and `/edit` in the sheet URL |

Fallback: `GOOGLE_SHEETS_WEBHOOK_URL` + `GOOGLE_SHEETS_WEBHOOK_SECRET` (Apps Script in `connectors/google_sheets_webhook.gs`).

### Dedicated clinical workbook (required for clinical cases)

Clinical questions/cases use a separate direct Sheets route and never write to
`GOOGLE_SHEET_ID`. Set:

| Variable | Value |
|---|---|
| `CLINICAL_SHEET_ID` | `1Te-dD6B9USOzURbTjMoZQgYtDeoygwR6QRGeHHGAzaQ` |
| `CLINICAL_SHEET_TAB` | approved restricted tab name; optional, otherwise the first existing tab is resolved |

Share this workbook with the same service-account email as **Editor**:

`https://docs.google.com/spreadsheets/d/1Te-dD6B9USOzURbTjMoZQgYtDeoygwR6QRGeHHGAzaQ/edit`

The clinical connector uses `GOOGLE_SERVICE_ACCOUNT_JSON` directly. It does not
use the general operational webhook as a fallback, so a sharing/API error must
be fixed on this workbook rather than silently mixing the data into the general
sheet.

## 3️⃣ Google Drive — ⚠️ verify share
Code: v0.8 read sync (`connectors/google_workspace.py`, OAuth) + service-account folder probe.

1. Same service account — no new key.
2. Enable **Google Drive API** (done with step 2 above).
3. Right-click the target folder → Share → service-account email (Editor).

| Variable | Value |
|---|---|
| `GOOGLE_DRIVE_FOLDER_ID` | folder id (last segment of the Drive folder URL) |

Used for: live share verification, and as the landing folder for new Docs (letters/reports).

## 4️⃣ Google Docs — 🆕 connector added
Code: `connectors/google_docs_service.py`.

1. Same service account.
2. Enable **Google Docs API**.
3. Share your letter/report Doc with the service-account email (Editor).

| Variable | Value |
|---|---|
| `GOOGLE_DOCS_DOCUMENT_ID` | default document for read/append (id between `/d/` and `/edit`) |
| `GOOGLE_DRIVE_FOLDER_ID` | optional — new documents are moved into this folder |

```bash
python3 -m connectors.google_docs_service status
python3 -m connectors.google_docs_service read
python3 -m connectors.google_docs_service create "خطاب رسمي" "نص الخطاب…"
python3 -m connectors.google_docs_service append "ملحق…"
```

Safety: documents are **drafts only** — nothing is emailed or shared from the connector;
external sends stay behind the human approval queue.

## 5️⃣ Google Calendar — ⚠️ priority 1 (meeting Sept 14)
Code: `connectors/calendar_actions.py` (+ Telegram reminder ledger).

1. Enable **Google Calendar API**.
2. Calendar ⚙️ Settings → your calendar → **Share with specific people** →
   service-account email → **Make changes to events**.
3. Same settings page → **Integrate calendar** → copy the **Calendar ID**.

| Variable | Value |
|---|---|
| `GOOGLE_CALENDAR_ID` | the real calendar id — the literal `primary` only works for OAuth, **not** for service accounts |
| `MANAGER_TIMEZONE` | optional, default `Asia/Riyadh` |

## 6️⃣ GitHub — ⚠️ verify env
Code: `connectors/github_live.py` (read-only: recent commits, open PRs).

1. github.com → Settings → Developer settings → Personal access tokens →
   scopes `repo` (+ `workflow`).
2. Copy the token immediately — it is shown once.

| Variable | Value |
|---|---|
| `GITHUB_TOKEN` | the PAT |
| `AI_OS_GITHUB_REPO` | optional, default `addn2030-svg/personal-ai-agent` |

---

## 7️⃣ YouTube Search — ✅ works with zero config
Code: `connectors/web_search.py` (read-only: verified `watch?v=` URLs only,
phones/e-mails/ID runs stripped from queries before any external call).

- No key needed: DuckDuckGo provider, automatic when the user asks for video links.
- Optional, more reliable: enable **YouTube Data API v3** in Google Cloud →
  create an API key restricted to that API → set `YOUTUBE_API_KEY`.
- Bot usage: `/youtube كلمات البحث` — or just ask for video links in any message.
- Verify where the bot runs (needs internet):
  `python3 -m connectors.web_search --check` or `--guide videosearch`.

| Variable | Value |
|---|---|
| `YOUTUBE_API_KEY` | optional; any API error falls back to the no-key provider |

---

## 8️⃣ Kimi API — optional overflow after Gemini's ~20 questions/day
Code: `connectors/model_gateway.py`, `connectors/model_router.py`.

Gemini free/low tiers often stop after about **20 questions per day**. Kimi
(Moonshot) is the overflow route: ordinary Telegram questions keep working after
Gemini returns 429/quota. Clinical questions stay on Gemini unless you
explicitly set `AI_CLINICAL_PROVIDER=kimi`.

1. Sign in at [platform.moonshot.ai](https://platform.moonshot.ai) (international)
   or [platform.moonshot.cn](https://platform.moonshot.cn) (China).
2. Console → **API Keys** → create a key. Copy it once.
3. Add the variables in Railway → Variables. Never paste the key in chat or git.

| Variable | Required | Value |
|---|---|---|
| `KIMI_API_KEY` | for overflow | Moonshot/Kimi secret. `MOONSHOT_API_KEY` is also accepted |
| `KIMI_MODEL` | optional | default `kimi-k2.5` (`kimi-k3`, `kimi-k2.6`, `moonshot-v1-128k` also work) |
| `KIMI_BASE_URL` | optional | default `https://api.moonshot.ai/v1` (China: `https://api.moonshot.cn/v1`) |
| `GEMINI_FALLBACK_KIMI` | optional | default `1` — overflow on Gemini quota. Set `0` to disable |
| `AI_MODEL_PROVIDER` | optional | keep `gemini` for overflow-only, or set `kimi` to skip Gemini entirely |

```bash
python3 -m connectors.connection_setup --guide kimi
python3 -m connectors.connection_setup --live
```

Telegram: `/ai_status` and `/kimi_test`.

---

## 9️⃣ Supabase — ☁️ نسخ الحالة خارج الخادم (اختياري لكن موصى به)

Code: `connectors/supabase_client.py` (REST بلا اعتماديات) · `connectors/supabase_state.py`
(نسخ/استعادة). الهدف: نسخة كاملة موقّعة ببصمة خارج Railway، لأن الـVolume وحده هو
نقطة الفشل الوحيدة اليوم (`docs/agent3-p0-adjudication.md`).

1. supabase.com/dashboard → المشروع → **Connect** (أو **Settings → API Keys**).
2. انسخ **Project URL** → `SUPABASE_URL` (شكله `https://<ref>.supabase.co`
   — لا تنسخ رابط اللوحة).
3. للقراءة: **publishable/anon key** → `SUPABASE_ANON_KEY`.
   للكتابة: **secret/service_role key** → `SUPABASE_SERVICE_ROLE_KEY` (خادم فقط).
4. شغّل SQL الإعداد مرة واحدة في SQL Editor: `python3 -m connectors.supabase_client --sql`.
5. فعّل الدفع: `SUPABASE_WRITE_ENABLED=1`.

| Variable | Required | ملاحظة |
|---|---|---|
| `SUPABASE_URL` | ✅ | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | ○ | قراءة فقط عبر RLS |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ للكتابة | **خادم فقط** — لا متصفح ولا Git ولا محادثة |
| `SUPABASE_WRITE_ENABLED` | ✅ للكتابة | `1` وإلا تبقى الكتابة مغلقة |

```bash
python3 -m connectors.supabase_client --check     # الإعداد (بلا شبكة)
python3 -m connectors.supabase_client --live      # اتصال حقيقي
python3 -m connectors.supabase_state push --reason "manual"
python3 -m connectors.supabase_state list
python3 -m connectors.supabase_state restore --id N          # معاينة
python3 -m connectors.supabase_state restore --id N --apply  # كتابة فعلية
```

Telegram: `/backup_now` نسخة الآن · `/backups` آخر النسخ.
الرحلة الكاملة والاستعادة وحل المشاكل: `docs/supabase-setup.md`.

---

## 📋 Environment variable summary

| Integration | Required | Optional |
|---|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN` | — |
| Operational Sheets | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID` | webhook pair |
| Clinical Sheets | `GOOGLE_SERVICE_ACCOUNT_JSON`, `CLINICAL_SHEET_ID` | `CLINICAL_SHEET_TAB` |
| Drive | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_FOLDER_ID` | — |
| Docs | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DOCS_DOCUMENT_ID` | `GOOGLE_DRIVE_FOLDER_ID` |
| Calendar | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_CALENDAR_ID` | `MANAGER_TIMEZONE` |
| GitHub | `GITHUB_TOKEN` | `AI_OS_GITHUB_REPO` |
| Gemini API | `GEMINI_API_KEY` | `GEMINI_MODEL` |
| Kimi API (Gemini 20/day overflow) | — | `KIMI_API_KEY`, `KIMI_MODEL`, `KIMI_BASE_URL` |
| YouTube search | — | `YOUTUBE_API_KEY` |
| Supabase backups | `SUPABASE_URL` (+ `SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_WRITE_ENABLED=1` to write) | `SUPABASE_ANON_KEY`, `SUPABASE_STATE_TABLE` |

## 🎯 Setup order
1. **Calendar** — most urgent (meeting Sept 14).
2. **Docs** — formal letters/reports now work through the new connector.
3. **GitHub** — code backup.

## Note on the two Google auth paths
- **Service account** (this guide): Sheets, Docs, Calendar actions, Drive share verification.
  Works headless on Railway; you share each asset with the service-account email.
- **OAuth desktop client** (`secrets/google-oauth-client.json`, v0.8): Gmail read,
  recent Drive file listing. A service account cannot read personal Gmail without
  domain-wide delegation, so that read path stays on OAuth.
