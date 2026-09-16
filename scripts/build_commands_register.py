#!/usr/bin/env python3
"""Build docs/history/telegram-commands.xlsx + .md + .csv — one row per Telegram command.
Re-run: python3 scripts/build_commands_register.py   (needs openpyxl)"""
from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

OUT = Path(__file__).resolve().parent.parent / "docs" / "history"

# (command, usage, purpose, group, introduced, version line, module, external side-effect?)
C = [
    ("/start", "/start", "Start the bot and show the full menu", "Basics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/help", "/help", "Show the command list", "Basics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/profile", "/profile", "Short professional profile", "Basics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/sources", "/sources", "Count knowledge sources, skills and materials", "Basics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/selftest", "/selftest", "Check Telegram and core system components", "Diagnostics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/storage_status", "/storage_status", "Check the Sheets storage connection on demand", "Diagnostics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/bedrock_test", "/bedrock_test", "Tiny probe of Claude + lean specialist on Bedrock", "Diagnostics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/context_test", "/context_test tomorrow", "Test Calendar/Sheets context without AI tokens", "Diagnostics", "2026-08-22", "Telegram v1", "connectors/telegram_bot.py", "No"),
    ("/approve", "/approve", "Pending-approvals panel with interactive buttons (C2 hash gate)", "Chief of Staff", "2026-08-22", "AI OS v0.4.x", "engine/telegram_bot.py", "Only after approval"),
    ("/decisions", "/decisions", "Open decision requests with buttons", "Chief of Staff", "2026-08-22", "AI OS v0.4.x", "engine/telegram_bot.py", "No"),
    ("/tasks", "/tasks", "Top open tasks", "Chief of Staff", "2026-08-22", "AI OS v0.4.x", "engine/telegram_bot.py", "No"),
    ("/door", "/door", "Weekly life door of the day", "Life OS", "2026-08-22", "AI OS v0.4.x", "engine/telegram_bot.py", "No"),
    ("/okr", "/okr", "Track objectives and key results", "Life OS", "2026-08-22", "AI OS v0.4.x", "engine/telegram_bot.py", "No"),
    ("/reviews", "/reviews", "Today's learning-engine reviews", "Learning", "2026-08-22", "AI OS v0.4", "engine/telegram_bot.py", "No"),
    ("/answer", "/answer LR-001 85", "Score a learning review", "Learning", "2026-08-22", "AI OS v0.4", "engine/telegram_bot.py", "No"),
    ("/mastery", "/mastery", "Concept mastery map", "Learning", "2026-08-22", "AI OS v0.4", "engine/telegram_bot.py", "No"),
    ("/brief", "/brief", "Executive brief: live Sheets + Calendar snapshot, diffs, blockers, decisions → Executive_Brief tab", "Clinical / Rehab", "2026-08-24", "Rehab v1.3 → Direct Brief v2.1 → Exec Brief v3", "connectors/brief_runtime.py", "Writes Sheet tab"),
    ("/memory", "/memory", "Show provenance-aware memory for the current topic", "Memory", "2026-08-25", "Memory", "engine/context_service.py", "No"),
    ("/memory_status", "/memory_status", "Memory store health and verified save receipts", "Memory", "2026-08-25", "Memory", "engine/context_service.py", "No"),
    ("/confirm_memory", "/confirm_memory", "Confirm a pending memory entry", "Memory", "2026-08-25", "Memory", "engine/context_service.py", "No"),
    ("/update_memory", "/update_memory", "Update / correct a memory entry", "Memory", "2026-08-25", "Memory", "engine/context_service.py", "No"),
    ("/delegate", "/delegate auto|claude|gpt|gemini task", "Delegate a task to a specialist model (auto = manager picks)", "AI Team", "2026-08-28", "Prod v0.6", "connectors/task_delegation.py", "No"),
    ("/agents", "/agents", "Status of the model team and routes", "AI Team", "2026-08-28", "Prod v0.6", "connectors/task_delegation.py", "No"),
    ("/council", "/council question", "Review by the whole team", "AI Team", "2026-08-28", "Prod v0.6", "connectors/task_delegation.py", "No"),
    ("/mission", "/mission [lean|standard|deep] goal", "Token-budgeted multi-model mission", "AI Team", "2026-08-28", "Mission v0.7–v0.9", "connectors/team_orchestrator.py, lean_missions.py", "No"),
    ("/google_access", "/google_access", "Google gateway diagnostics", "Diagnostics", "2026-08-28", "Prod v0.7/0.8", "(rolled back #21)", "No"),
    ("/manager", "/manager request", "Super Manager: links, finds gaps, recommends", "Chief of Staff", "2026-08-30", "Super Manager v1.1", "connectors/super_manager.py", "No"),
    ("/manager_shadow", "/manager_shadow request", "Compare Legacy vs Super Manager with no external effect", "Chief of Staff", "2026-08-30", "Canary", "connectors/manager_fast_canary.py", "No"),
    ("/manager_status", "/manager_status", "Manager layer status", "Chief of Staff", "2026-08-30", "Super Manager v1.1", "connectors/super_manager.py", "No"),
    ("/capabilities", "/capabilities", "Runtime capability truth — what the agent can actually do now", "Governance", "2026-08-31", "Capability Truth", "connectors/capability_runtime.py", "No"),
    ("/act", "/act natural-language request", "Natural-language action executor (deadline, reminder, report…) with receipt", "Actions", "2026-08-31", "NL Actions", "connectors/action_runtime.py", "Only after approval"),
    ("/action_status", "/action_status", "Status of pending / executed actions", "Actions", "2026-08-31", "NL Actions", "connectors/action_runtime.py", "No"),
    ("/approve_action", "/approve_action ID", "Approve a queued action", "Actions", "2026-08-31", "NL Actions", "connectors/action_runtime.py", "Yes (approved)"),
    ("/reject_action", "/reject_action ID", "Reject a queued action", "Actions", "2026-08-31", "NL Actions", "connectors/action_runtime.py", "No"),
    ("/shop", "/shop item", "Read-only deal scout", "Commerce", "2026-09-01", "Commerce", "connectors/commerce_scout.py", "No"),
    ("/prepare_order", "/prepare_order …", "Prepare an order draft (≤ $100 pilot cap)", "Commerce", "2026-09-01", "Commerce", "connectors/commerce_runtime.py", "No"),
    ("/approve_order", "/approve_order ID CODE", "Approve an order via trusted checkout adapter", "Commerce", "2026-09-01", "Commerce", "connectors/commerce_checkout.py", "Yes (approved, capped)"),
    ("/commerce_status", "/commerce_status", "Commerce agent status and caps", "Commerce", "2026-09-01", "Commerce", "connectors/commerce_runtime.py", "No"),
    ("/commerce_test", "/commerce_test", "Safe sandbox smoke test", "Commerce", "2026-09-01", "Commerce", "connectors/commerce_sandbox.py", "No"),
    ("/books", "/books [query]", "Learning-shelf book retrieval (fast path)", "Knowledge", "2026-09-04", "Books v3.0", "engine/books_context.py", "No"),
    ("/masteros", "/masteros", "Master OS architecture summary and state", "Master OS", "2026-09-09", "AI OS v0.9 Master OS", "engine/telegram_bot.py", "No"),
    ("/schedule", "/schedule", "Scheduled automation table (Asia/Riyadh, 11 jobs)", "Master OS", "2026-09-09", "AI OS v0.9 Master OS", "engine/scheduler.py", "No"),
    ("/today_actions", "/today_actions (alias /today-actions)", "Queue today's actions into the approval queue", "Master OS", "2026-09-09", "AI OS v0.9 Master OS", "engine/scheduler.py", "No (drafts)"),
    ("/mind_maps", "/mind_maps (alias /mindmaps)", "Mind-map library (Mermaid)", "Master OS", "2026-09-09", "AI OS v0.9 Master OS", "engine/mindmap.py", "No"),
    ("/audio_digests", "/audio_digests (alias /digests)", "Audio digest pipeline status", "Master OS", "2026-09-09", "AI OS v0.9 Master OS", "engine/audio_digest.py", "No"),
    ("/run", "/run", "Run due scheduler jobs now as drafts", "Master OS", "2026-09-09", "AI OS v0.9 Master OS", "engine/scheduler.py", "No (drafts)"),
    ("/diag", "/diag", "Status of the 7 connection channels (presence-only, offline)", "Diagnostics", "2026-09-09", "v0.9 live wiring", "engine/telegram_bot.py", "No"),
    ("/proactive", "/proactive", "Proactive Chief of Staff status (standing orders, alerts, ledger)", "Proactive", "2026-09-11", "Proactive v1.0.2", "engine/proactive.py", "No"),
    ("/sweep", "/sweep", "Run one proactive cycle now", "Proactive", "2026-09-11", "Proactive v1.0.2", "engine/proactive.py", "Telegram alert only"),
    ("/proactive_test", "/proactive_test", "Push a test urgent alert to Telegram", "Proactive", "2026-09-11", "Proactive v1.0.2", "engine/proactive.py", "Telegram alert only"),
    ("/content", "/content [platform] idea", "Content Creator orchestra (researcher → critic → creator) → preview", "Content", "2026-09-11", "Content", "connectors/content_runtime.py", "No"),
    ("/approve_content", "/approve_content ID CODE", "Send approved version to Buffer, save receipt", "Content", "2026-09-11", "Content", "connectors/buffer_publisher.py", "Yes (approved)"),
    ("/reject_content", "/reject_content ID", "Reject a draft with no external effect", "Content", "2026-09-11", "Content", "connectors/content_runtime.py", "No"),
    ("/content_status", "/content_status", "Content Creator, Buffer and latest drafts status", "Content", "2026-09-11", "Content", "connectors/content_runtime.py", "No"),
    ("/content_sheet", "/content_sheet [Q-001]", "Pull idea from Life Pulse publishing sheet → PUBLISH_QUEUE draft", "Content", "2026-09-11", "Content", "connectors/content_sheet.py", "Writes Sheet row"),
    ("/content_sheet_status", "/content_sheet_status", "Check read access to the publishing sheet", "Content", "2026-09-11", "Content", "connectors/content_sheet.py", "No"),
    ("/design_content", "/design_content ID|idea", "Gemini image generation for a content draft", "Content", "2026-09-12", "Content", "connectors/content_media.py", "No"),
    ("/video_content", "/video_content ID|idea", "Gemini video generation for a content draft", "Content", "2026-09-12", "Content", "connectors/content_media.py", "No"),
    ("/media_status", "/media_status", "Media generation status", "Content", "2026-09-12", "Content", "connectors/content_media.py", "No"),
    ("/time", "/time", "Real-clock liveness probe (Asia/Riyadh)", "Diagnostics", "2026-09-14", "Prod fix #105", "engine/runtime_clock.py", "No"),
    ("/youtube", "/youtube keywords (alias /search)", "Verified YouTube search — real watch?v= links only, PII stripped", "Search", "2026-09-15", "Web search", "connectors/web_search.py", "Read-only web"),
]

CLI = [
    ("python3 engine/manager.py --loop", "Run fast (15 min) + full (06:00) manager cycles", "2026-08-21"),
    ("python3 engine/approve.py approve A-001 --hash …", "Approve a queued action with its SHA-256 hash", "2026-08-21"),
    ("python3 engine/voice_call.py demo A|B|C|D|E / ingest call.json", "Process an inbound call transcript", "2026-08-21"),
    ("python3 engine/learning_engine.py outline LP-001", "Generate ILPC outline for a learning plan", "2026-08-21"),
    ("python3 engine/export_for_chat.py", "Export context for ChatGPT / VS Code", "2026-08-21"),
    ("python3 engine/import_drive.py [--sources]", "Import sheet / knowledge sources from Drive", "2026-08-21"),
    ("python3 -m connectors.web_search --check", "Check YouTube/DuckDuckGo search from the bot environment", "2026-09-15"),
    ("python3 engine/drive_tree.py render|checklist", "Render Master OS Drive tree / folder checklist", "2026-09-09"),
    ("python3 engine/scheduler.py today-actions", "Queue today's scheduled actions as drafts", "2026-09-09"),
    ("python3 engine/proactive.py sweep|brief|status|orders", "Proactive loop CLI", "2026-09-11"),
    ("python3 engine/proactive.py push-test", "Test urgent Telegram alert channel", "2026-09-11"),
    ("python3 engine/proactive.py review [--apply]", "Weekly acceptance review with bounded self-tuning", "2026-09-11"),
    ("python3 engine/proactive.py threshold|matrix|status", "Money threshold policy / autonomy matrix", "2026-09-15"),
    ("bash scripts/verify_money_threshold.sh", "Full verification of the autopay < 375 SAR path", "2026-09-15"),
    ("python3 engine/system_status.py --layers --schedule --finance --proactive", "One-command system status (14 layers)", "2026-09-15"),
    ("order-disable SO-00x / undo PA-xxxx / pause --hours 4 / feedback PA-xxxx good|much|never", "Proactive control verbs", "2026-09-11"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hdr = ["#", "Command", "Usage", "Purpose", "Group", "Introduced", "Version line", "Module", "External side-effect"]
    rows = [(i + 1, *c) for i, c in enumerate(C)]

    wb = Workbook()
    ws = wb.active
    ws.title = "Telegram Commands"
    ws.append(hdr)
    for r in rows:
        ws.append(list(r))
    for i, w in enumerate([5, 22, 36, 62, 16, 12, 30, 40, 22], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for c in ws[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1E293B"), Font(bold=True, color="FFFFFF")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    t = Table(displayName="Commands", ref=f"A1:{get_column_letter(len(hdr))}{len(rows) + 1}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)

    ws2 = wb.create_sheet("CLI Commands")
    ws2.append(["#", "CLI command", "Purpose", "Introduced"])
    for i, c in enumerate(CLI):
        ws2.append([i + 1, *c])
    for i, w in enumerate([5, 70, 60, 12], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    for c in ws2[1]:
        c.fill, c.font = PatternFill("solid", fgColor="1E293B"), Font(bold=True, color="FFFFFF")
    ws2.freeze_panes = "A2"
    wb.save(OUT / "telegram-commands.xlsx")

    with (OUT / "telegram-commands.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(hdr); w.writerows(rows)

    md = ["# Telegram & CLI Command Register", "",
          f"{len(C)} Telegram commands (plus aliases) and {len(CLI)} CLI entry points, ordered by introduction date. "
          "Spreadsheet: `telegram-commands.xlsx` / `telegram-commands.csv`.", "",
          "## Telegram commands", "",
          "| # | Command | Usage | Purpose | Group | Introduced | Version line | Module | External side-effect |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    md += ["", "## CLI commands", "", "| # | Command | Purpose | Introduced |", "|---|---|---|---|"]
    for i, c in enumerate(CLI):
        md.append(f"| {i + 1} | `{c[0]}` | {c[1]} | {c[2]} |")
    md += ["", "## Commands by group", ""]
    groups: dict[str, list[str]] = {}
    for c in C:
        groups.setdefault(c[3], []).append(c[0])
    for g, cmds in groups.items():
        md.append(f"- **{g}** ({len(cmds)}): " + " ".join(f"`{x}`" for x in cmds))
    (OUT / "telegram-commands.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {len(C)} commands + {len(CLI)} CLI entries")


if __name__ == "__main__":
    main()
