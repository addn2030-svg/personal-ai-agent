#!/usr/bin/env python3
"""Generate docs/history/evolution-infographic.svg from the repository's real history.

Dependency-free (pure SVG string building). Metrics below were measured with
`git ls-tree` at the last commit of each day on `main` (see docs/history/README.md).
Re-run:  python3 scripts/build_history_infographic.py
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "history" / "evolution-infographic.svg"

# date, engine modules, connectors, test files, prompt packs, docs, commits that day
DAILY = [
    ("08-21", 13, 0, 0, 7, 3, 14),
    ("08-22", 51, 8, 1, 13, 12, 40),
    ("08-24", 52, 13, 3, 14, 13, 7),
    ("08-25", 53, 14, 5, 14, 13, 14),
    ("08-27", 53, 16, 6, 14, 13, 1),
    ("08-28", 53, 26, 16, 14, 13, 68),
    ("08-29", 53, 27, 16, 14, 13, 20),
    ("08-30", 54, 30, 21, 14, 14, 30),
    ("08-31", 54, 38, 24, 14, 14, 22),
    ("09-01", 54, 43, 25, 14, 14, 13),
    ("09-02", 54, 44, 25, 14, 14, 3),
    ("09-03", 54, 44, 25, 14, 14, 6),
    ("09-04", 55, 44, 25, 14, 14, 6),
    ("09-08", 55, 46, 28, 14, 16, 4),
    ("09-09", 60, 46, 33, 15, 18, 8),
    ("09-11", 61, 51, 37, 16, 20, 13),
    ("09-12", 61, 52, 39, 16, 20, 3),
    ("09-14", 62, 54, 42, 16, 21, 3),
    ("09-15", 64, 57, 44, 16, 29, 5),
]

# Milestone cards: (date, version, title, colour, bullets)
MILESTONES = [
    ("Aug 21", "v0.2 → v0.4.1", "Foundation", "#2563eb",
     ["Unified StateStore + SHA-256 approval gate", "Manager loop (fast 15m / full 06:00)",
      "Voice-call intake · Adaptive teaching (ILPC)", "Autostart 24/7 · Drive & ChatGPT bridges"]),
    ("Aug 22", "v0.5 → v0.9", "Chief of Staff Core", "#7c3aed",
     ["Orchestrator, permissions, memory, RAG", "RCJY rehab leadership training pack",
      "Self-improving loop · Trust & change intel", "Live Gmail/Calendar/Drive/GitHub/Telegram"]),
    ("Aug 22–25", "Telegram Prod v1", "Mobile Runtime", "#0891b2",
     ["Railway container · Bedrock Claude replies", "AWS Transcribe voice notes",
      "Sheets intelligence + secure Apps Script webhook", "Provenance-first semantic memory"]),
    ("Aug 24", "Rehab v1.3 / Ph 1.5", "Clinical Layer", "#059669",
     ["Executive /brief discovery + supervisor form", "Pre-visit intelligence (case-code only)",
      "Safety triage URGENT/PRIORITY/ROUTINE", "Webhook mode + privacy hardening (P0)"]),
    ("Aug 27–28", "Prod v0.5a → v0.9.6", "Multi-Model Team", "#d97706",
     ["OpenRouter primary + Bedrock fallback", "Task delegation · Mission orchestrator",
      "Claude/GPT/Gemini direct APIs · Nova Micro", "Guarded NL Calendar actions (mobile)"]),
    ("Aug 29–31", "Gate 0.5 / WO-8", "Safety & Truth", "#dc2626",
     ["Direct Brief v2.1 (Sheets + Calendar)", "StateStore concurrency + fail-closed dates",
      "Capability Truth · Natural Action Executor", "Super Manager v1.1 · FAST canary"]),
    ("Sep 1–4", "Commerce / Bridge", "Extensions", "#db2777",
     ["Commerce Agent ($100 pilot caps)", "First-party /chat Bridge API",
      "Strategic shadow DEV CI runner", "Books context (learning shelf) v3.0"]),
    ("Sep 8–9", "v0.9 Master OS", "Knowledge & Automation", "#4f46e5",
     ["Google Docs connector + connection doctor", "Riyadh scheduler (11 jobs)",
      "Mermaid mind maps · Audio digests", "ElevenLabs channel · /diag"]),
    ("Sep 11–12", "v1.0 → v1.0.3", "Proactive CoS", "#16a34a",
     ["observe→remember→predict→score→decide→act", "8 standing orders · L0–L4 autonomy",
      "Urgent Telegram alerts · self-tuning review", "Buffer publisher · Content Creator · Gemini media"]),
    ("Sep 14–15", "v2.0 / v1.1", "Finance & Autopay", "#ea580c",
     ["Real-clock anchor · Drive project memory", "Unified Finance Hub v2.0",
      "Dormant layers activated (14/14)", "Money threshold: autopay < 375 SAR"]),
]

W, H = 1600, 2080
PAD = 60


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build() -> str:
    o: list[str] = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             f'font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif">')
    o.append('<defs>'
             '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0" stop-color="#0f172a"/><stop offset="1" stop-color="#1e293b"/></linearGradient>'
             '<linearGradient id="area" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0" stop-color="#38bdf8" stop-opacity="0.55"/><stop offset="1" stop-color="#38bdf8" stop-opacity="0.05"/></linearGradient>'
             '</defs>')
    o.append(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')

    # ---------- Header ----------
    o.append(f'<text x="{PAD}" y="70" font-size="40" font-weight="800" fill="#f8fafc">Rehabilitation Chief-of-Staff Agent — Evolution Timeline</text>')
    o.append(f'<text x="{PAD}" y="104" font-size="18" fill="#94a3b8">Abdulrahman AI OS · addn2030-svg/personal-ai-agent · 21 Aug 2026 → 15 Sep 2026 (26 days) · 304 commits · 108 merged PRs</text>')

    # ---------- KPI tiles ----------
    kpis = [("64", "engine modules", "13 → 64"), ("57", "connectors", "0 → 57"), ("44", "test files", "373 tests"),
            ("60+", "Telegram commands", "/brief … /sweep"), ("29K", "lines of Python", "engine+connectors+tests"),
            ("16", "prompt packs", "clinical · proactive · …")]
    tw = (W - 2 * PAD - 5 * 16) / 6
    for i, (big, label, sub) in enumerate(kpis):
        x = PAD + i * (tw + 16)
        o.append(f'<rect x="{x}" y="130" width="{tw}" height="96" rx="14" fill="#1e293b" stroke="#334155"/>')
        o.append(f'<text x="{x + 18}" y="176" font-size="36" font-weight="800" fill="#38bdf8">{big}</text>')
        o.append(f'<text x="{x + 18}" y="200" font-size="14" fill="#e2e8f0">{esc(label)}</text>')
        o.append(f'<text x="{x + 18}" y="218" font-size="12" fill="#64748b">{esc(sub)}</text>')

    # ---------- Growth chart ----------
    cx, cy, cw, ch = PAD, 270, W - 2 * PAD, 360
    o.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" rx="16" fill="#0b1220" stroke="#334155"/>')
    o.append(f'<text x="{cx + 20}" y="{cy + 32}" font-size="20" font-weight="700" fill="#f1f5f9">Codebase growth by day (last commit on main each day)</text>')
    px, py, pw, ph = cx + 60, cy + 60, cw - 100, ch - 120
    ymax = 70
    for v in range(0, ymax + 1, 10):
        yy = py + ph - v / ymax * ph
        o.append(f'<line x1="{px}" y1="{yy:.1f}" x2="{px + pw}" y2="{yy:.1f}" stroke="#1e293b"/>')
        o.append(f'<text x="{px - 10}" y="{yy + 4:.1f}" font-size="11" fill="#64748b" text-anchor="end">{v}</text>')
    n = len(DAILY)
    xs = [px + i * pw / (n - 1) for i in range(n)]

    def poly(idx: int) -> str:
        return " ".join(f"{xs[i]:.1f},{py + ph - DAILY[i][idx] / ymax * ph:.1f}" for i in range(n))

    # area under engine modules
    o.append(f'<polygon points="{xs[0]:.1f},{py + ph} {poly(1)} {xs[-1]:.1f},{py + ph}" fill="url(#area)"/>')
    series = [(1, "#38bdf8", "Engine modules"), (2, "#a78bfa", "Connectors"), (3, "#34d399", "Test files"),
              (5, "#fbbf24", "Docs"), (4, "#f472b6", "Prompt packs")]
    for idx, col, _ in series:
        o.append(f'<polyline points="{poly(idx)}" fill="none" stroke="{col}" stroke-width="3" stroke-linejoin="round"/>')
        for i in range(n):
            yy = py + ph - DAILY[i][idx] / ymax * ph
            o.append(f'<circle cx="{xs[i]:.1f}" cy="{yy:.1f}" r="3.5" fill="{col}"/>')
    for i, d in enumerate(DAILY):
        o.append(f'<text x="{xs[i]:.1f}" y="{py + ph + 18}" font-size="11" fill="#94a3b8" text-anchor="middle">{d[0]}</text>')
    # commit bars (secondary, faint)
    bw = pw / n * 0.5
    for i, d in enumerate(DAILY):
        hgt = d[6] / 70 * ph * 0.6
        o.append(f'<rect x="{xs[i] - bw / 2:.1f}" y="{py + ph - hgt:.1f}" width="{bw:.1f}" height="{hgt:.1f}" fill="#f8fafc" opacity="0.06"/>')
        o.append(f'<text x="{xs[i]:.1f}" y="{py + ph + 34}" font-size="10" fill="#475569" text-anchor="middle">{d[6]}c</text>')
    # legend
    lx = px
    for idx, col, name in series:
        o.append(f'<rect x="{lx}" y="{cy + ch - 26}" width="14" height="14" rx="3" fill="{col}"/>')
        o.append(f'<text x="{lx + 20}" y="{cy + ch - 14}" font-size="12" fill="#cbd5e1">{name}</text>')
        lx += 150
    o.append(f'<text x="{lx + 10}" y="{cy + ch - 14}" font-size="12" fill="#64748b">grey bars / "Nc" = commits that day</text>')

    # ---------- Milestone timeline ----------
    ty = cy + ch + 50
    o.append(f'<text x="{PAD}" y="{ty}" font-size="24" font-weight="800" fill="#f8fafc">Release milestones</text>')
    ty += 24
    card_w = (W - 2 * PAD - 60) / 2
    card_h = 150
    gap = 26
    spine_x = W / 2
    o.append(f'<line x1="{spine_x}" y1="{ty}" x2="{spine_x}" y2="{ty + len(MILESTONES) / 2 * (card_h + gap) + 40}" stroke="#334155" stroke-width="4" stroke-dasharray="2 6"/>')
    for i, (date, ver, title, col, bullets) in enumerate(MILESTONES):
        row = i // 2
        left = i % 2 == 0
        y = ty + row * (card_h + gap) + (0 if left else (card_h + gap) / 2)
        x = PAD if left else spine_x + 30
        # connector dot on spine
        dot_y = y + 30
        o.append(f'<circle cx="{spine_x}" cy="{dot_y}" r="9" fill="{col}" stroke="#0f172a" stroke-width="3"/>')
        o.append(f'<line x1="{x + card_w if left else spine_x}" y1="{dot_y}" x2="{spine_x if left else x}" y2="{dot_y}" stroke="{col}" stroke-width="2"/>')
        o.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="14" fill="#0b1220" stroke="{col}" stroke-width="1.5"/>')
        o.append(f'<rect x="{x}" y="{y}" width="8" height="{card_h}" rx="4" fill="{col}"/>')
        o.append(f'<text x="{x + 22}" y="{y + 28}" font-size="13" font-weight="700" fill="{col}">{esc(date.upper())}</text>')
        o.append(f'<text x="{x + card_w - 16}" y="{y + 28}" font-size="12" fill="#94a3b8" text-anchor="end">{esc(ver)}</text>')
        o.append(f'<text x="{x + 22}" y="{y + 54}" font-size="19" font-weight="800" fill="#f8fafc">{esc(title)}</text>')
        for j, b in enumerate(bullets):
            o.append(f'<text x="{x + 22}" y="{y + 78 + j * 18}" font-size="12.5" fill="#cbd5e1">• {esc(b)}</text>')

    # ---------- Capability stack (bottom) ----------
    sy = ty + 5 * (card_h + gap) + 70
    o.append(f'<text x="{PAD}" y="{sy}" font-size="24" font-weight="800" fill="#f8fafc">Capability layers at v2.0 (15 Sep 2026)</text>')
    layers = [
        ("Governance", "#dc2626", "SHA-256 approval gate · L0–L4 autonomy · Capability Truth · audit.jsonl · money ≤375 SAR hard cap"),
        ("Proactive Chief of Staff", "#16a34a", "8 standing orders · open loops · 6 alerts/day · quiet hours 22:00–06:30 · undo · self-tuning review"),
        ("Clinical & Rehab Ops", "#059669", "Executive /brief · supervisor form · pre-visit intelligence (case-code only) · clinical prompt pack · voice-call intake"),
        ("Knowledge & Learning", "#4f46e5", "RAG · provenance memory · books shelf · ILPC teaching engine · mind maps · audio digests · Drive tree"),
        ("Automation & Finance", "#ea580c", "Riyadh scheduler (11 jobs) · manager fast/full loop · Finance Hub v2.0 · OKR · energy log · asset registry"),
        ("Integrations", "#0891b2", "Telegram webhook · Google Sheets/Docs/Calendar/Drive/Gmail · GitHub · Buffer · Bedrock/OpenRouter/Gemini/GPT · ElevenLabs · AWS Transcribe"),
    ]
    ly = sy + 20
    for name, col, desc in layers:
        o.append(f'<rect x="{PAD}" y="{ly}" width="{W - 2 * PAD}" height="52" rx="10" fill="#0b1220" stroke="#334155"/>')
        o.append(f'<rect x="{PAD}" y="{ly}" width="230" height="52" rx="10" fill="{col}"/>')
        o.append(f'<text x="{PAD + 16}" y="{ly + 32}" font-size="15" font-weight="800" fill="#ffffff">{esc(name)}</text>')
        o.append(f'<text x="{PAD + 250}" y="{ly + 32}" font-size="13.5" fill="#e2e8f0">{esc(desc)}</text>')
        ly += 60

    o.append(f'<text x="{PAD}" y="{H - 24}" font-size="12" fill="#475569">Source: git history of main (304 commits / 108 PRs), README release notes, docs/v*.md. Generated by scripts/build_history_infographic.py — the agent never sends external side-effects without approval.</text>')
    o.append('</svg>')
    return "\n".join(o)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
