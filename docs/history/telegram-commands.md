# Telegram & CLI Command Register

61 Telegram commands (plus aliases) and 16 CLI entry points, ordered by introduction date. Spreadsheet: `telegram-commands.xlsx` / `telegram-commands.csv`.

## Telegram commands

| # | Command | Usage | Purpose | Group | Introduced | Version line | Module | External side-effect |
|---|---|---|---|---|---|---|---|---|
| 1 | /start | /start | Start the bot and show the full menu | Basics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 2 | /help | /help | Show the command list | Basics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 3 | /profile | /profile | Short professional profile | Basics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 4 | /sources | /sources | Count knowledge sources, skills and materials | Basics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 5 | /selftest | /selftest | Check Telegram and core system components | Diagnostics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 6 | /storage_status | /storage_status | Check the Sheets storage connection on demand | Diagnostics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 7 | /bedrock_test | /bedrock_test | Tiny probe of Claude + lean specialist on Bedrock | Diagnostics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 8 | /context_test | /context_test tomorrow | Test Calendar/Sheets context without AI tokens | Diagnostics | 2026-08-22 | Telegram v1 | connectors/telegram_bot.py | No |
| 9 | /approve | /approve | Pending-approvals panel with interactive buttons (C2 hash gate) | Chief of Staff | 2026-08-22 | AI OS v0.4.x | engine/telegram_bot.py | Only after approval |
| 10 | /decisions | /decisions | Open decision requests with buttons | Chief of Staff | 2026-08-22 | AI OS v0.4.x | engine/telegram_bot.py | No |
| 11 | /tasks | /tasks | Top open tasks | Chief of Staff | 2026-08-22 | AI OS v0.4.x | engine/telegram_bot.py | No |
| 12 | /door | /door | Weekly life door of the day | Life OS | 2026-08-22 | AI OS v0.4.x | engine/telegram_bot.py | No |
| 13 | /okr | /okr | Track objectives and key results | Life OS | 2026-08-22 | AI OS v0.4.x | engine/telegram_bot.py | No |
| 14 | /reviews | /reviews | Today's learning-engine reviews | Learning | 2026-08-22 | AI OS v0.4 | engine/telegram_bot.py | No |
| 15 | /answer | /answer LR-001 85 | Score a learning review | Learning | 2026-08-22 | AI OS v0.4 | engine/telegram_bot.py | No |
| 16 | /mastery | /mastery | Concept mastery map | Learning | 2026-08-22 | AI OS v0.4 | engine/telegram_bot.py | No |
| 17 | /brief | /brief | Executive brief: live Sheets + Calendar snapshot, diffs, blockers, decisions → Executive_Brief tab | Clinical / Rehab | 2026-08-24 | Rehab v1.3 → Direct Brief v2.1 → Exec Brief v3 | connectors/brief_runtime.py | Writes Sheet tab |
| 18 | /memory | /memory | Show provenance-aware memory for the current topic | Memory | 2026-08-25 | Memory | engine/context_service.py | No |
| 19 | /memory_status | /memory_status | Memory store health and verified save receipts | Memory | 2026-08-25 | Memory | engine/context_service.py | No |
| 20 | /confirm_memory | /confirm_memory | Confirm a pending memory entry | Memory | 2026-08-25 | Memory | engine/context_service.py | No |
| 21 | /update_memory | /update_memory | Update / correct a memory entry | Memory | 2026-08-25 | Memory | engine/context_service.py | No |
| 22 | /delegate | /delegate auto\|claude\|gpt\|gemini task | Delegate a task to a specialist model (auto = manager picks) | AI Team | 2026-08-28 | Prod v0.6 | connectors/task_delegation.py | No |
| 23 | /agents | /agents | Status of the model team and routes | AI Team | 2026-08-28 | Prod v0.6 | connectors/task_delegation.py | No |
| 24 | /council | /council question | Review by the whole team | AI Team | 2026-08-28 | Prod v0.6 | connectors/task_delegation.py | No |
| 25 | /mission | /mission [lean\|standard\|deep] goal | Token-budgeted multi-model mission | AI Team | 2026-08-28 | Mission v0.7–v0.9 | connectors/team_orchestrator.py, lean_missions.py | No |
| 26 | /google_access | /google_access | Google gateway diagnostics | Diagnostics | 2026-08-28 | Prod v0.7/0.8 | (rolled back #21) | No |
| 27 | /manager | /manager request | Super Manager: links, finds gaps, recommends | Chief of Staff | 2026-08-30 | Super Manager v1.1 | connectors/super_manager.py | No |
| 28 | /manager_shadow | /manager_shadow request | Compare Legacy vs Super Manager with no external effect | Chief of Staff | 2026-08-30 | Canary | connectors/manager_fast_canary.py | No |
| 29 | /manager_status | /manager_status | Manager layer status | Chief of Staff | 2026-08-30 | Super Manager v1.1 | connectors/super_manager.py | No |
| 30 | /capabilities | /capabilities | Runtime capability truth — what the agent can actually do now | Governance | 2026-08-31 | Capability Truth | connectors/capability_runtime.py | No |
| 31 | /act | /act natural-language request | Natural-language action executor (deadline, reminder, report…) with receipt | Actions | 2026-08-31 | NL Actions | connectors/action_runtime.py | Only after approval |
| 32 | /action_status | /action_status | Status of pending / executed actions | Actions | 2026-08-31 | NL Actions | connectors/action_runtime.py | No |
| 33 | /approve_action | /approve_action ID | Approve a queued action | Actions | 2026-08-31 | NL Actions | connectors/action_runtime.py | Yes (approved) |
| 34 | /reject_action | /reject_action ID | Reject a queued action | Actions | 2026-08-31 | NL Actions | connectors/action_runtime.py | No |
| 35 | /shop | /shop item | Read-only deal scout | Commerce | 2026-09-01 | Commerce | connectors/commerce_scout.py | No |
| 36 | /prepare_order | /prepare_order … | Prepare an order draft (≤ $100 pilot cap) | Commerce | 2026-09-01 | Commerce | connectors/commerce_runtime.py | No |
| 37 | /approve_order | /approve_order ID CODE | Approve an order via trusted checkout adapter | Commerce | 2026-09-01 | Commerce | connectors/commerce_checkout.py | Yes (approved, capped) |
| 38 | /commerce_status | /commerce_status | Commerce agent status and caps | Commerce | 2026-09-01 | Commerce | connectors/commerce_runtime.py | No |
| 39 | /commerce_test | /commerce_test | Safe sandbox smoke test | Commerce | 2026-09-01 | Commerce | connectors/commerce_sandbox.py | No |
| 40 | /books | /books [query] | Learning-shelf book retrieval (fast path) | Knowledge | 2026-09-04 | Books v3.0 | engine/books_context.py | No |
| 41 | /masteros | /masteros | Master OS architecture summary and state | Master OS | 2026-09-09 | AI OS v0.9 Master OS | engine/telegram_bot.py | No |
| 42 | /schedule | /schedule | Scheduled automation table (Asia/Riyadh, 11 jobs) | Master OS | 2026-09-09 | AI OS v0.9 Master OS | engine/scheduler.py | No |
| 43 | /today_actions | /today_actions (alias /today-actions) | Queue today's actions into the approval queue | Master OS | 2026-09-09 | AI OS v0.9 Master OS | engine/scheduler.py | No (drafts) |
| 44 | /mind_maps | /mind_maps (alias /mindmaps) | Mind-map library (Mermaid) | Master OS | 2026-09-09 | AI OS v0.9 Master OS | engine/mindmap.py | No |
| 45 | /audio_digests | /audio_digests (alias /digests) | Audio digest pipeline status | Master OS | 2026-09-09 | AI OS v0.9 Master OS | engine/audio_digest.py | No |
| 46 | /run | /run | Run due scheduler jobs now as drafts | Master OS | 2026-09-09 | AI OS v0.9 Master OS | engine/scheduler.py | No (drafts) |
| 47 | /diag | /diag | Status of the 7 connection channels (presence-only, offline) | Diagnostics | 2026-09-09 | v0.9 live wiring | engine/telegram_bot.py | No |
| 48 | /proactive | /proactive | Proactive Chief of Staff status (standing orders, alerts, ledger) | Proactive | 2026-09-11 | Proactive v1.0.2 | engine/proactive.py | No |
| 49 | /sweep | /sweep | Run one proactive cycle now | Proactive | 2026-09-11 | Proactive v1.0.2 | engine/proactive.py | Telegram alert only |
| 50 | /proactive_test | /proactive_test | Push a test urgent alert to Telegram | Proactive | 2026-09-11 | Proactive v1.0.2 | engine/proactive.py | Telegram alert only |
| 51 | /content | /content [platform] idea | Content Creator orchestra (researcher → critic → creator) → preview | Content | 2026-09-11 | Content | connectors/content_runtime.py | No |
| 52 | /approve_content | /approve_content ID CODE | Send approved version to Buffer, save receipt | Content | 2026-09-11 | Content | connectors/buffer_publisher.py | Yes (approved) |
| 53 | /reject_content | /reject_content ID | Reject a draft with no external effect | Content | 2026-09-11 | Content | connectors/content_runtime.py | No |
| 54 | /content_status | /content_status | Content Creator, Buffer and latest drafts status | Content | 2026-09-11 | Content | connectors/content_runtime.py | No |
| 55 | /content_sheet | /content_sheet [Q-001] | Pull idea from Life Pulse publishing sheet → PUBLISH_QUEUE draft | Content | 2026-09-11 | Content | connectors/content_sheet.py | Writes Sheet row |
| 56 | /content_sheet_status | /content_sheet_status | Check read access to the publishing sheet | Content | 2026-09-11 | Content | connectors/content_sheet.py | No |
| 57 | /design_content | /design_content ID\|idea | Gemini image generation for a content draft | Content | 2026-09-12 | Content | connectors/content_media.py | No |
| 58 | /video_content | /video_content ID\|idea | Gemini video generation for a content draft | Content | 2026-09-12 | Content | connectors/content_media.py | No |
| 59 | /media_status | /media_status | Media generation status | Content | 2026-09-12 | Content | connectors/content_media.py | No |
| 60 | /time | /time | Real-clock liveness probe (Asia/Riyadh) | Diagnostics | 2026-09-14 | Prod fix #105 | engine/runtime_clock.py | No |
| 61 | /youtube | /youtube keywords (alias /search) | Verified YouTube search — real watch?v= links only, PII stripped | Search | 2026-09-15 | Web search | connectors/web_search.py | Read-only web |

## CLI commands

| # | Command | Purpose | Introduced |
|---|---|---|---|
| 1 | `python3 engine/manager.py --loop` | Run fast (15 min) + full (06:00) manager cycles | 2026-08-21 |
| 2 | `python3 engine/approve.py approve A-001 --hash …` | Approve a queued action with its SHA-256 hash | 2026-08-21 |
| 3 | `python3 engine/voice_call.py demo A|B|C|D|E / ingest call.json` | Process an inbound call transcript | 2026-08-21 |
| 4 | `python3 engine/learning_engine.py outline LP-001` | Generate ILPC outline for a learning plan | 2026-08-21 |
| 5 | `python3 engine/export_for_chat.py` | Export context for ChatGPT / VS Code | 2026-08-21 |
| 6 | `python3 engine/import_drive.py [--sources]` | Import sheet / knowledge sources from Drive | 2026-08-21 |
| 7 | `python3 -m connectors.web_search --check` | Check YouTube/DuckDuckGo search from the bot environment | 2026-09-15 |
| 8 | `python3 engine/drive_tree.py render|checklist` | Render Master OS Drive tree / folder checklist | 2026-09-09 |
| 9 | `python3 engine/scheduler.py today-actions` | Queue today's scheduled actions as drafts | 2026-09-09 |
| 10 | `python3 engine/proactive.py sweep|brief|status|orders` | Proactive loop CLI | 2026-09-11 |
| 11 | `python3 engine/proactive.py push-test` | Test urgent Telegram alert channel | 2026-09-11 |
| 12 | `python3 engine/proactive.py review [--apply]` | Weekly acceptance review with bounded self-tuning | 2026-09-11 |
| 13 | `python3 engine/proactive.py threshold|matrix|status` | Money threshold policy / autonomy matrix | 2026-09-15 |
| 14 | `bash scripts/verify_money_threshold.sh` | Full verification of the autopay < 375 SAR path | 2026-09-15 |
| 15 | `python3 engine/system_status.py --layers --schedule --finance --proactive` | One-command system status (14 layers) | 2026-09-15 |
| 16 | `order-disable SO-00x / undo PA-xxxx / pause --hours 4 / feedback PA-xxxx good|much|never` | Proactive control verbs | 2026-09-11 |

## Commands by group

- **Basics** (4): `/start` `/help` `/profile` `/sources`
- **Diagnostics** (7): `/selftest` `/storage_status` `/bedrock_test` `/context_test` `/google_access` `/diag` `/time`
- **Chief of Staff** (6): `/approve` `/decisions` `/tasks` `/manager` `/manager_shadow` `/manager_status`
- **Life OS** (2): `/door` `/okr`
- **Learning** (3): `/reviews` `/answer` `/mastery`
- **Clinical / Rehab** (1): `/brief`
- **Memory** (4): `/memory` `/memory_status` `/confirm_memory` `/update_memory`
- **AI Team** (4): `/delegate` `/agents` `/council` `/mission`
- **Governance** (1): `/capabilities`
- **Actions** (4): `/act` `/action_status` `/approve_action` `/reject_action`
- **Commerce** (5): `/shop` `/prepare_order` `/approve_order` `/commerce_status` `/commerce_test`
- **Knowledge** (1): `/books`
- **Master OS** (6): `/masteros` `/schedule` `/today_actions` `/mind_maps` `/audio_digests` `/run`
- **Proactive** (3): `/proactive` `/sweep` `/proactive_test`
- **Content** (9): `/content` `/approve_content` `/reject_content` `/content_status` `/content_sheet` `/content_sheet_status` `/design_content` `/video_content` `/media_status`
- **Search** (1): `/youtube`
