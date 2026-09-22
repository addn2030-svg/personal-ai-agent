# -*- coding: utf-8 -*-
"""ABH-Memory Hub — routing registry, provenance envelope and governance gate.

The hub is the single entry point for a multi-project workspace. It does three
jobs, all deterministic (no model calls, no network):

  1. ROUTE   parse ``root_memory.mmd`` and expose the project routing table.
  2. ENVELOPE attach the provenance record envelope required by
             ``docs/information-governance.md`` to any new artefact.
  3. VALIDATE enforce the hub's own structural and language guardrails:
             - every in-repo path referenced by the hub must exist
             - every active project must have a charter
             - no patient-identifiable data may appear in hub artefacts
             - no medical guarantee / exaggerated claim language (GLOBAL_RULES §2)

Usage:
    python3 -m engine.memory_hub route
    python3 -m engine.memory_hub validate [--strict]
    python3 -m engine.memory_hub envelope --project P3 --type RECOMMENDATION \
        --source "user brief 2026-09-22" --summary "..."
    python3 -m engine.memory_hub scan path/to/file.md [...]

Design notes:
    * Fail-closed. An unreadable hub map or a missing charter is a FAIL, never a
      silent pass.
    * The claim guardrail is deliberately conservative: it reports candidate
      violations for human review rather than rewriting text. A false positive
      costs a read; a false negative costs a regulatory exposure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HUB_MAP = os.path.join(BASE, "root_memory.mmd")
MEMORY_DIR = os.path.join(BASE, "memory")
PROJECTS_DIR = os.path.join(MEMORY_DIR, "projects")
GLOBAL_RULES = os.path.join(MEMORY_DIR, "GLOBAL_RULES.md")
SPRINTS_DIR = os.path.join(MEMORY_DIR, "sprints")

TZ = dt.timezone(dt.timedelta(hours=3))  # Arabia Standard Time

# ---------------------------------------------------------------------------
# Project registry — the routing table. root_memory.mmd is the human-readable
# view; this dict is the machine-readable source of truth for validation.
# ---------------------------------------------------------------------------
PROJECTS = {
    "P1": {
        "id": "P1",
        "name": "Personal AI Agent",
        "status": "active",
        "domain": "Prompt engineering · custom agent frameworks",
        "charter": "memory/projects/01-personal-ai-agent.md",
        "repo": "https://github.com/addn2030-svg/personal-ai-agent",
        "owner": "Abdulrahman Bakor Howsawy",
        "sensitivity": "internal",
        "clinical": False,
    },
    "P2": {
        "id": "P2",
        "name": "Telegram AI Course",
        "status": "active",
        "domain": "Educational content creation · curriculum design",
        "charter": "memory/projects/02-telegram-ai-course.md",
        "repo": None,
        "owner": "Abdulrahman Bakor Howsawy",
        "sensitivity": "internal",
        "clinical": False,
    },
    "P3": {
        "id": "P3",
        "name": "Pulse of Life Rehab & Home Visit",
        "status": "active",
        "domain": "Jubail home-visit pilot · NKT/ANF protocols · marketing ops",
        "charter": "memory/projects/03-pulse-of-life-home-rehab.md",
        "repo": None,
        "owner": "Abdulrahman Bakor Howsawy",
        "sensitivity": "clinical-adjacent",
        "clinical": True,
        "current_sprint": "memory/sprints/2026-W39-pulse-of-life-home-visit.md",
    },
    "P4": {
        "id": "P4",
        "name": "ABH-Memory Hub",
        "status": "active",
        "domain": "Multi-project routing · governance gates · hub artefacts and sprint oversight",
        "charter": "memory/projects/04-abh-memory-hub.md",
        "repo": "https://github.com/addn2030-svg/personal-ai-agent",
        "owner": "Abdulrahman Bakor Howsawy",
        "sensitivity": "internal",
        "clinical": False,
    },
}

# ---------------------------------------------------------------------------
# Guardrail patterns
# ---------------------------------------------------------------------------

# GLOBAL_RULES §2 — medical guarantees and exaggerated claims.
# Each entry: (rule id, human label, compiled pattern).
CLAIM_PATTERNS = [
    # CLM-1 deliberately matches the VERB form ("cures back pain", "will cure")
    # and not the bare noun ("cure"), because policy and charter documents must
    # be able to name the prohibited class — "No cure language" — without
    # tripping their own guardrail. A customer-facing assertion always uses the
    # verb or an explicit promise construction.
    ("CLM-1", "cure / elimination promise", re.compile(
        r"\b(cures|curing|will\s+cure|can\s+cure|we\s+cure|"
        r"eliminates?|eliminat(?:e|ing)\s+(?:the\s+)?pain|"
        r"eradicates?|removes?\s+(?:the\s+)?(?:disease|condition|pain)|"
        r"permanent(?:ly)?\s+(?:fix|cure|solution)|heals?\s+(?:it\s+)?completely)\b",
        re.I)),
    # CLM-2 likewise targets ASSERTIONS of certainty ("guaranteed results",
    # "100% effective", "we guarantee") rather than the abstract noun
    # ("guarantees", "no guarantee"), which governance text must be free to use.
    ("CLM-2", "certainty / guarantee language", re.compile(
        r"\b(guaranteed|we\s+guarantee|i\s+guarantee|"
        r"guarantee\s+(?:of|you|results?|recovery|relief|pain\s+relief|success|a\s+cure)|"
        r"100\s*(?:%|percent)\s*(?:effective|safe|success(?:ful)?|cure|guaranteed|results?)|"
        r"proven\s+to\s+(?:cure|heal|reverse)|"
        r"assured\s+(?:recovery|results?|relief)|"
        r"(?:will|shall)\s+(?:definitely|certainly|surely)\s+(?:recover|heal|improve)|"
        r"risk[- ]free\s+(?:treatment|therapy))\b", re.I)),
    ("CLM-3", "fixed recovery timeline", re.compile(
        r"\b(?:(?:full|complete|total)\s+recovery\s+in\s+\d+|"
        r"(?:recover|healed|cured|pain[- ]free)\s+(?:in|within)\s+\d+\s+"
        r"(?:days?|weeks?|sessions?|months?)|"
        r"\d+\s+(?:days?|weeks?|sessions?)\s+to\s+(?:full\s+recovery|a\s+cure|being\s+cured))\b",
        re.I)),
    ("CLM-4", "superiority / ranking claim", re.compile(
        r"\b(?:best|number\s*one|no\.?\s*1|top[- ]rated|finest|greatest|"
        r"most\s+advanced|leading)\b[^\n]{0,60}?"
        r"\b(?:in|of|across)\s+(?:jubail|saudi|khobar|dammam|riyadh|jeddah|"
        r"the\s+(?:kingdom|region|city|eastern\s+province|gulf|middle\s+east))\b|"
        r"\bbetter\s+than\s+(?:hospital|clinic|physiotherapy|medical|the\s+clinic)\s*(?:care|treatment)?|"
        r"\bunmatched\b|\bsecond\s+to\s+none\b|\bworld[- ]class\s+(?:results?|recovery)\b",
        re.I)),
    ("CLM-5", "reversal / regeneration claim", re.compile(
        r"\b(?:(?:reverses?|reversing|reverse)\s+(?:the\s+)?"
        r"(?:damage|disease|paralysis|degeneration|progression|condition|"
        r"nerve|cartilage|disc|tissue|atrophy|arthritis|diabetes|stroke|aging|ageing)|"
        r"regenerates?|regenerating|"
        r"restores?\s+completely|"
        r"rebuilds?\s+(?:the\s+)?(?:nerve|cartilage|disc|tissue)\s+completely)\b",
        re.I)),
    ("CLM-6", "unverified endorsement / affiliation", re.compile(
        r"\b(?:rcjy|rchsp|ministry\s+of\s+health|moh|cbahi|sfda)[- ]"
        r"(?:approved|endorsed|certified|accredited|licensed|recommended)\b", re.I)),
    ("CLM-7", "outcome promise tied to a named condition", re.compile(
        r"\b(?:stroke|paralysis|parkinson|multiple\s+sclerosis|cerebral\s+palsy|"
        r"spinal\s+(?:cord\s+)?injury|disc\s+herniation)\s+"
        r"(?:patients?\s+)?(?:will|shall|can\s+expect\s+to)\s+"
        r"(?:recover|walk\s+again|return\s+to\s+normal|be\s+cured)\b", re.I)),
]

# GLOBAL_RULES §3 — patient-identifiable data and secrets.
PRIVACY_PATTERNS = [
    ("PRV-1", "medical record number", re.compile(r"\b(?:mrn|medical\s+record\s+(?:no|number))\s*[:#]?\s*\d", re.I)),
    ("PRV-2", "national ID / iqama reference", re.compile(r"\b(?:national\s+id|iqama|هوية|رقم\s*الهوية)\s*[:#]?\s*\d", re.I)),
    ("PRV-3", "named-patient label", re.compile(r"\bpatient\s*(?:name)?\s*[:=]\s*[A-Z][a-z]+\s+[A-Z][a-z]+", re.I)),
    ("PRV-4", "Saudi mobile number in a clinical context", re.compile(r"(?:patient|client|case)[^\n]{0,60}(?:\+?966\s?5|05)\d[\s-]?\d{3}[\s-]?\d{4}", re.I)),
    ("PRV-5", "credential / secret literal", re.compile(r"\b(?:api[_-]?key|secret|token|password|bearer|private[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}", re.I)),
]

# Paths that are exempt from the claim scan because they legitimately quote
# prohibited language in order to forbid it, or are third-party source records.
SCAN_EXEMPT = {
    os.path.join(BASE, "memory", "GLOBAL_RULES.md"),
    os.path.abspath(__file__),
}

# Lines that state a PROHIBITION rather than make a claim. Governance documents
# (charters, rule sets, sprint plans) must be able to name the forbidden class —
# "Zero medical guarantees", "No cure language", "copy drifts into guarantees" —
# without tripping the guardrail they exist to enforce.
#
# This heuristic is documented and deliberately narrow. It is NOT the primary
# control: customer-facing marketing copy is still reviewed by a human and must
# carry a recorded sign-off (GLOBAL_RULES §6, sprint gate G6). The scan reports
# candidates for review; it never rewrites text.
PROHIBITION_LINE = re.compile(
    r"(?:^|\||\*\*)\s*(?:zero|no|never|not|prohibited|avoid|barred|forbidden|"
    r"do\s+not|don't|must\s+not|shall\s+not|omit)\b"
    r"|drifts?\s+into\b"
    r"|\bclaim[- ]language\s+guardrail\b"
    r"|\bprohibited\s+pattern\b",
    re.I)

# A claim pattern quoted as a counter-example, e.g. the "Prohibited" column of a
# guardrail table: | "Guaranteed pain relief" | "A structured assessment…" |
QUOTED_COUNTER_EXAMPLE = re.compile(r'"\s*[^"]{3,120}\s*"')

RECORD_TYPES = {
    "FACT", "USER_STATEMENT", "DOCUMENT", "AI_INFERENCE",
    "RECOMMENDATION", "REQUEST", "DECISION",
}
CONFIDENCE_CLASSES = {"CONFIRMED", "DOCUMENT_SUPPORTED", "INFERRED", "VERIFY", "HISTORICAL"}


def _read(path: str) -> str:
    """Read a UTF-8 text file, always closing the handle."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def parse_hub_map(path: str = HUB_MAP) -> dict:
    """Parse the Mermaid mindmap into a nested branch/leaf structure.

    Returns ``{"root": str, "branches": [{"name":..,"leaves":[..],
    "sub_branches":[{"name":..,"leaves":[..]}]}]}``. Fail-closed: raises
    ``FileNotFoundError`` / ``ValueError`` rather than returning an empty hub.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"hub map missing: {path}")
    raw = _read(path)
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines or lines[0].strip() != "mindmap":
        raise ValueError("hub map must start with a 'mindmap' declaration")

    root_match = re.match(r"^\s*root\(\((.+?)\)\)\s*$", lines[1])
    if not root_match:
        raise ValueError("hub map must declare root((...)) on the second line")
    root = root_match.group(1).strip()

    # Stack-based tree build using relative indentation, so 2-space, 4-space or
    # uneven-but-monotonic maps all parse correctly.
    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    body = lines[2:]
    if not body:
        raise ValueError("hub map declares no branches")

    base = indent_of(body[0])
    if base <= 0:
        raise ValueError("hub map branches must be indented under root((...))")

    # Relative nesting: a node is a child of the nearest preceding node with a
    # strictly smaller indent, and a sibling of the nearest with an equal indent.
    # Uneven but monotonic indent steps are accepted; a node indented *less* than
    # the branch level is a structural error.
    tree: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for line in body:
        ind = indent_of(line)
        text = line.strip()
        if ind < base:
            raise ValueError(
                f"node indented above branch level ({ind} < {base}): {text!r}")
        if not text:
            raise ValueError("empty hub map node")
        node = {"name": text, "children": []}
        while stack and stack[-1][0] >= ind:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            tree.append(node)
        stack.append((ind, node))

    # Normalise into the hub's three-tier view: branch → sub_branch → leaves.
    # Deeper tiers are flattened into leaf text with an indented marker so no
    # routing information is lost.
    def flatten_deeper(node: dict, prefix: str = "") -> list[str]:
        out: list[str] = []
        for child in node["children"]:
            out.append(prefix + child["name"])
            out.extend(flatten_deeper(child, prefix + "  "))
        return out

    branches: list[dict] = []
    for top in tree:
        branch = {"name": top["name"], "leaves": [], "sub_branches": []}
        for second in top["children"]:
            if second["children"] and any(c["children"] for c in second["children"]):
                sub = {"name": second["name"], "leaves": []}
                for third in second["children"]:
                    sub["leaves"].append(third["name"])
                    sub["leaves"].extend(flatten_deeper(third, "  "))
                branch["sub_branches"].append(sub)
            else:
                branch["sub_branches"].append(
                    {"name": second["name"], "leaves": flatten_deeper(second)})
        branches.append(branch)

    return {"root": root, "branches": branches}


def _git_ignored(rel_path: str) -> bool:
    """True when git itself ignores this path (runtime state, never committed)."""
    try:
        import subprocess
        proc = subprocess.run(
            ["git", "check-ignore", "-q", rel_path],
            cwd=BASE, capture_output=True, timeout=10,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001 - git unavailable: fall back to prefixes
        return False


# Runtime state locations: correct to reference, legitimately absent from a fresh
# clone. Downgraded to a warning ONLY when git also ignores them — a runtime path
# that is *not* ignored means state could be committed, which is itself a defect.
RUNTIME_PREFIXES = ("data/",)


def referenced_paths(hub: dict) -> list[str]:
    """Collect every in-repo path referenced anywhere in the hub map."""
    out: list[str] = []
    path_re = re.compile(r"(?:^|\s)((?:memory|knowledge|docs|engine|connectors|tests|data|prompts|scripts|skills|reports)/[\w./-]+)")
    for branch in hub["branches"]:
        nodes = [branch["name"], *branch["leaves"]]
        for sub in branch.get("sub_branches", []):
            nodes.append(sub["name"])
            nodes.extend(sub["leaves"])
        for node in nodes:
            out.extend(m.group(1) for m in path_re.finditer(node))
    return sorted(set(out))


def routing_table() -> list[dict]:
    """Machine-readable routing table for all registered projects."""
    return [dict(p) for p in PROJECTS.values()]


def route(project_ref: str) -> dict | None:
    """Resolve 'P3', 'p3', '3' or a name fragment to a project record."""
    key = (project_ref or "").strip()
    if not key:
        return None
    if key.upper() in PROJECTS:
        return dict(PROJECTS[key.upper()])
    if key.isdigit() and f"P{int(key)}" in PROJECTS:
        return dict(PROJECTS[f"P{int(key)}"])
    low = key.lower()
    for proj in PROJECTS.values():
        if low in proj["name"].lower() or low in proj["domain"].lower():
            return dict(proj)
    return None


# ---------------------------------------------------------------------------
# Provenance envelope
# ---------------------------------------------------------------------------

def envelope(project: str, record_type: str, source_ref: str, summary: str,
             confidence: str = "INFERRED", owner: str | None = None,
             sensitivity: str = "normal", next_action: str | None = None,
             due_at: str | None = None, status: str = "NEW") -> dict:
    """Build the record envelope required by docs/information-governance.md.

    Raises ``ValueError`` on an unknown record type or confidence class — the
    vocabulary is closed on purpose so the hub cannot drift into unlabeled state.
    """
    rtype = (record_type or "").strip().upper()
    if rtype not in RECORD_TYPES:
        raise ValueError(f"record_type must be one of {sorted(RECORD_TYPES)}, got {record_type!r}")
    conf = (confidence or "").strip().upper()
    if conf not in CONFIDENCE_CLASSES:
        raise ValueError(f"confidence must be one of {sorted(CONFIDENCE_CLASSES)}, got {confidence!r}")
    proj = route(project)
    if proj is None:
        raise ValueError(f"unknown project reference: {project!r}")
    now = dt.datetime.now(TZ)
    digest = hashlib.sha256(f"{proj['id']}|{rtype}|{summary}".encode("utf-8")).hexdigest()[:10]
    return {
        "record_id": f"{proj['id']}-{rtype[:3]}-{digest}",
        "record_type": rtype,
        "source_type": "USER_BRIEF" if "brief" in source_ref.lower() else "DOCUMENT",
        "source_ref": source_ref,
        "captured_at": now.isoformat(timespec="seconds"),
        "effective_date": now.date().isoformat(),
        "last_verified": now.date().isoformat(),
        "confidence": conf,
        "owner": owner or proj["owner"],
        "related_project": proj["id"],
        "related_area": proj["domain"],
        "status": status,
        "summary": summary,
        "next_action": next_action,
        "due_at": due_at,
        "sensitivity": sensitivity,
    }


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def _is_claim_exempt_line(line: str) -> bool:
    """True when a line states a prohibition or quotes a counter-example.

    Claim-category only. Privacy findings are NEVER exempted — an identifier is a
    breach wherever it appears, including inside a table cell or a quoted example.
    """
    if PROHIBITION_LINE.search(line):
        return True
    # A guardrail table cell quoting the forbidden phrasing: | "Guaranteed…" | … |
    if line.lstrip().startswith("|") and QUOTED_COUNTER_EXAMPLE.search(line):
        return True
    return False


# Cap per rule per line so one pathological line cannot flood the report. Every
# distinct match is still reported up to this limit — using a single .search()
# here was a guardrail hole: a second violation on the same line went unseen.
MAX_FINDINGS_PER_RULE_PER_LINE = 5


def scan_text(text: str) -> list[dict]:
    """Return guardrail findings for a block of text.

    Reports **every** match, not just the first per line: ``finditer`` rather than
    ``search``. Claim findings are skipped on lines that state a prohibition or
    quote a counter-example; privacy findings are never skipped.
    """
    findings: list[dict] = []

    def emit(category, rule, label, lineno, match, line):
        findings.append({
            "severity": "FAIL", "category": category, "rule": rule,
            "label": label, "line": lineno, "match": match,
            "context": line.strip()[:160],
        })

    for lineno, line in enumerate(text.splitlines(), start=1):
        if not _is_claim_exempt_line(line):
            for rule, label, pattern in CLAIM_PATTERNS:
                for i, m in enumerate(pattern.finditer(line)):
                    if i >= MAX_FINDINGS_PER_RULE_PER_LINE:
                        break
                    emit("claim", rule, label, lineno, m.group(0), line)
        for rule, label, pattern in PRIVACY_PATTERNS:
            for i, m in enumerate(pattern.finditer(line)):
                if i >= MAX_FINDINGS_PER_RULE_PER_LINE:
                    break
                emit("privacy", rule, label, lineno, m.group(0), line)
    return findings


def scan_file(path: str) -> list[dict]:
    abs_path = os.path.abspath(path)
    if abs_path in SCAN_EXEMPT:
        return []
    try:
        text = _read(abs_path)
    except OSError as exc:
        return [{"severity": "FAIL", "category": "io", "rule": "IO-1",
                 "label": "unreadable file", "line": 0, "match": str(exc),
                 "context": abs_path}]
    hits = scan_text(text)
    for hit in hits:
        hit["file"] = os.path.relpath(abs_path, BASE)
    return hits


def hub_artefacts() -> list[str]:
    """Every Markdown artefact owned by the hub (charters, sprints, rules)."""
    out = [GLOBAL_RULES] if os.path.exists(GLOBAL_RULES) else []
    for directory in (PROJECTS_DIR, SPRINTS_DIR):
        if os.path.isdir(directory):
            out.extend(
                os.path.join(directory, name)
                for name in sorted(os.listdir(directory))
                if name.endswith(".md")
            )
    return out


def validate(strict: bool = False) -> dict:
    """Run every hub gate. Returns a report dict; never raises on findings.

    Fail-closed checks:
      V1 hub map parses
      V2 every referenced in-repo path exists
      V3 every registered project exists in the hub map
      V4 every active project has a charter on disk
      V5 charters declare the required sections
      V6 hub artefacts are free of guarantee/exaggeration language (§2)
      V7 hub artefacts are free of patient-identifiable data and secrets (§3)
      V8 global rules file exists and declares the clinical boundary
    """
    checks: list[dict] = []
    findings: list[dict] = []

    def record(cid: str, label: str, ok: bool, detail: str = "", items: list | None = None) -> None:
        checks.append({"id": cid, "label": label, "ok": bool(ok), "detail": detail,
                       "items": items or []})

    # V1 -------------------------------------------------------------------
    hub = None
    try:
        hub = parse_hub_map()
        record("V1", "hub map parses", True,
               f"root={hub['root']!r}, {len(hub['branches'])} top-level branches")
    except Exception as exc:  # noqa: BLE001 - fail-closed by design
        record("V1", "hub map parses", False, f"{type(exc).__name__}: {exc}")

    # V2 -------------------------------------------------------------------
    if hub is not None:
        refs = referenced_paths(hub)
        absent = [r for r in refs if not os.path.exists(os.path.join(BASE, r))]
        runtime_absent = [r for r in absent
                          if r.startswith(RUNTIME_PREFIXES) and _git_ignored(r)]
        missing = [r for r in absent if r not in runtime_absent]
        record("V2", "referenced paths exist", not missing,
               f"{len(refs) - len(absent)}/{len(refs)} resolved · "
               f"{len(runtime_absent)} runtime-state file(s) absent by design",
               missing)
        findings.extend({"severity": "FAIL", "category": "structure", "rule": "V2",
                         "label": "dangling hub reference", "line": 0, "match": m,
                         "context": "root_memory.mmd", "file": "root_memory.mmd"}
                        for m in missing)
        findings.extend({"severity": "WARN", "category": "structure", "rule": "V2W",
                         "label": "runtime state not yet materialised", "line": 0,
                         "match": w, "context": "created at runtime; git-ignored",
                         "file": "root_memory.mmd"} for w in runtime_absent)

    # V3 -------------------------------------------------------------------
    if hub is not None:
        flat = " ".join(
            node
            for branch in hub["branches"]
            for node in (
                [branch["name"], *branch["leaves"]]
                + [s["name"] for s in branch.get("sub_branches", [])]
                + [leaf for s in branch.get("sub_branches", []) for leaf in s["leaves"]]
            )
        )
        absent = [f"{pid} · {p['name']}" for pid, p in PROJECTS.items()
                  if p["id"] not in flat]
        record("V3", "projects registered in hub map", not absent,
               f"{len(PROJECTS) - len(absent)}/{len(PROJECTS)} present", absent)
        findings.extend({"severity": "FAIL", "category": "structure", "rule": "V3",
                         "label": "project missing from hub map", "line": 0,
                         "match": a, "context": "root_memory.mmd",
                         "file": "root_memory.mmd"} for a in absent)

    # V4 -------------------------------------------------------------------
    active = [p for p in PROJECTS.values() if p["status"] == "active"]
    no_charter = [p["id"] for p in active
                  if not os.path.exists(os.path.join(BASE, p["charter"]))]
    record("V4", "active projects have charters", not no_charter,
           f"{len(active) - len(no_charter)}/{len(active)} charters on disk", no_charter)
    findings.extend({"severity": "FAIL", "category": "structure", "rule": "V4",
                     "label": "missing project charter", "line": 0, "match": c,
                     "context": PROJECTS[c]["charter"], "file": PROJECTS[c]["charter"]}
                    for c in no_charter)

    # V5 -------------------------------------------------------------------
    required_sections = ["Scope", "Guardrails", "Current state", "Next actions"]
    incomplete: list[str] = []
    for proj in active:
        path = os.path.join(BASE, proj["charter"])
        if not os.path.exists(path):
            continue
        text = _read(path)
        headings = re.findall(r"^#{1,4}\s+(.+?)\s*$", text, re.M)
        missing = [s for s in required_sections
                   if not any(s.lower() in h.lower() for h in headings)]
        if missing:
            incomplete.append(f"{proj['id']}: missing {', '.join(missing)}")
    record("V5", "charters declare required sections", not incomplete,
           f"{len(active) - len(incomplete)}/{len(active)} complete", incomplete)
    findings.extend({"severity": "FAIL", "category": "structure", "rule": "V5",
                     "label": "charter section missing", "line": 0, "match": i,
                     "context": "charter", "file": "charter"} for i in incomplete)

    # V6 + V7 --------------------------------------------------------------
    artefacts = hub_artefacts()
    claim_hits: list[dict] = []
    privacy_hits: list[dict] = []
    for artefact in artefacts:
        for hit in scan_file(artefact):
            (privacy_hits if hit["category"] == "privacy" else claim_hits).append(hit)
    record("V6", "no medical guarantee / exaggerated claim language",
           not claim_hits, f"{len(artefacts)} artefacts scanned",
           [f"{h['file']}:{h['line']} [{h['rule']}] {h['match']!r}" for h in claim_hits])
    record("V7", "no patient-identifiable data or secrets",
           not privacy_hits, "privacy patterns applied",
           [f"{h['file']}:{h['line']} [{h['rule']}] {h['match']!r}" for h in privacy_hits])
    findings.extend(claim_hits)
    findings.extend(privacy_hits)

    # V8 -------------------------------------------------------------------
    if os.path.exists(GLOBAL_RULES):
        rules_text = _read(GLOBAL_RULES)
        declares = ("Zero medical guarantees" in rules_text
                    and "Patient-identifiable" in rules_text)
        record("V8", "global rules declare clinical + privacy boundary", declares,
               "memory/GLOBAL_RULES.md" if declares else "boundary language not found")
    else:
        record("V8", "global rules declare clinical + privacy boundary", False,
               "memory/GLOBAL_RULES.md missing")

    failed = [c for c in checks if not c["ok"]]
    warnings = [f for f in findings if f.get("severity") == "WARN"]
    report = {
        "hub": "ABH-Memory",
        "generated_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "strict": strict,
        "artefacts_scanned": [os.path.relpath(a, BASE) for a in artefacts],
        "projects": routing_table(),
        "checks": checks,
        "findings": findings,
        "warnings": warnings,
        "passed": not failed and (not warnings if strict else True),
        "summary": f"{len(checks) - len(failed)}/{len(checks)} gates passed"
                   + (f" · {len(warnings)} warning(s)" if warnings else ""),
    }
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(report: dict) -> int:
    print(f"\nABH-Memory hub validation — {report['generated_at']}")
    print("=" * 62)
    for check in report["checks"]:
        mark = "PASS" if check["ok"] else "FAIL"
        print(f"[{mark}] {check['id']} — {check['label']}")
        if check["detail"]:
            print(f"        {check['detail']}")
        for item in check["items"][:12]:
            print(f"        · {item}")
        if len(check["items"]) > 12:
            print(f"        · … and {len(check['items']) - 12} more")
    print("=" * 62)
    print(report["summary"])
    warns = report.get("warnings") or []
    if warns:
        print("\nWarnings (informational — runtime state not yet materialised):")
        for w in warns[:10]:
            print(f"  · {w['match']} — {w['context']}")
    if not report["passed"]:
        print("\nACTION REQUIRED — resolve every FAIL before publishing or "
              "committing hub artefacts.")
        return 1
    print("\nHub is consistent. Guardrails clean.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ABH-Memory workspace hub")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("route", help="print the project routing table")
    v = sub.add_parser("validate", help="run hub structural + language gates")
    v.add_argument("--strict", action="store_true",
                   help="reserved: treat warnings as failures")
    v.add_argument("--json", action="store_true", help="emit machine-readable report")

    e = sub.add_parser("envelope", help="build a provenance record envelope")
    e.add_argument("--project", required=True)
    e.add_argument("--type", required=True, dest="record_type")
    e.add_argument("--source", required=True)
    e.add_argument("--summary", required=True)
    e.add_argument("--confidence", default="INFERRED")
    e.add_argument("--owner", default=None)
    e.add_argument("--sensitivity", default="normal")
    e.add_argument("--next-action", default=None)
    e.add_argument("--due", default=None)

    s = sub.add_parser("scan", help="scan arbitrary files against the guardrails")
    s.add_argument("paths", nargs="+")

    args = parser.parse_args(argv)

    if args.command == "route":
        print(json.dumps(routing_table(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "validate":
        report = validate(strict=args.strict)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["passed"] else 1
        return _print_report(report)

    if args.command == "envelope":
        try:
            rec = envelope(args.project, args.record_type, args.source,
                           args.summary, args.confidence, args.owner,
                           args.sensitivity, args.next_action, args.due)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0

    if args.command == "scan":
        all_hits: list[dict] = []
        for path in args.paths:
            if not os.path.exists(path):
                print(f"ERROR: no such file: {path}", file=sys.stderr)
                return 2
            all_hits.extend(scan_file(path))
        if not all_hits:
            print(f"Scanned {len(args.paths)} file(s). No guardrail findings.")
            return 0
        for hit in all_hits:
            print(f"[FAIL] {hit.get('file', '?')}:{hit['line']} "
                  f"[{hit['rule']} · {hit['label']}] {hit['match']!r}")
            print(f"        {hit['context']}")
        print(f"\n{len(all_hits)} finding(s). Rewrite to hedged, sourced language.")
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
