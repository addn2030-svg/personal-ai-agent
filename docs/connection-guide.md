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

## 📋 Environment variable summary

| Integration | Required | Optional |
|---|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN` | — |
| Sheets | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID` | webhook pair |
| Drive | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_FOLDER_ID` | — |
| Docs | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DOCS_DOCUMENT_ID` | `GOOGLE_DRIVE_FOLDER_ID` |
| Calendar | `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_CALENDAR_ID` | `MANAGER_TIMEZONE` |
| GitHub | `GITHUB_TOKEN` | `AI_OS_GITHUB_REPO` |

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
