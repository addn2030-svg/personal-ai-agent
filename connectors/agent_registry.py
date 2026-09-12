# -*- coding: utf-8 -*-
"""Agent Registry — capability cards living inside the existing `sub_agents` section.

There is no second registry. A card is a row in ``StateStore["sub_agents"]`` that the
scheduler already knows about (``JOB_SPECS[].agent`` → ``AG-MORNING`` … ``AG-FINANCE``),
extended with the four fields that make routing checkable instead of guessable:

    capabilities[]     closed, verb-shaped identifiers — one active owner each
    input_schema       bounded contract (required keys + property types)
    confidence_floor   below it, output goes to review and never to state
    cost_class         low | medium | high — fed to the dispatching budget

Design rules (all enforced by code, not by instruction in a prompt):

1. A capability is ASCII snake_case and **starts with an action verb**
   (``draft_ops_directive``), never a domain noun (``clinical_documentation``).
   Prose capabilities are what make routing ambiguous at fleet scale.
2. A capability has exactly **one** active owner. A second declaration is rejected,
   with the fix stated in the error (split the capability, don't share it).
3. Registering an agent without a capability set or an input schema is rejected.
4. Changing ownership is explicit (``reassign_from=``) and audited — never implicit.

CLI:
    python3 -m connectors.agent_registry list
    python3 -m connectors.agent_registry capability draft_ops_directive
    python3 -m connectors.agent_registry check          # drift detector (exit 1 on drift)
    python3 -m connectors.agent_registry upgrade        # add cards to existing installs
"""
from __future__ import annotations

import re

from engine.store import Store, log_event

SECTION = "sub_agents"

# --------------------------------------------------------------------------- vocabulary
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
AGENT_ID_RE = re.compile(r"^AG-[A-Z0-9][A-Z0-9-]{1,31}$")

# A capability must open with an action verb. Adding a verb here is a deliberate
# registry-review action — that is the point: it is a closed vocabulary, not free text.
ACTION_PREFIXES = frozenset({
    "add", "apply", "archive", "assess", "audit", "build", "calculate", "capture",
    "challenge", "classify", "close", "compare", "compute", "confirm", "convert",
    "detect", "digest", "draft", "enrich", "escalate", "estimate", "evaluate",
    "extract", "forecast", "generate", "identify", "index", "ingest", "list", "log",
    "match", "measure", "merge", "monitor", "notify", "open", "plan", "prepare",
    "propose", "publish", "rank", "reconcile", "record", "render", "report",
    "resolve", "review", "route", "scan", "schedule", "score", "send", "split",
    "summarize", "synthesize", "track", "translate", "update", "validate", "verify",
})

PROPERTY_TYPES = ("string", "int", "float", "bool", "list", "object", "date")
INPUT_SCHEMA_KEYS = ("required", "properties")
COST_CLASSES = ("low", "medium", "high")
STATUSES = ("active", "paused", "retired")
INVOKED_BY = ("scheduler", "connector", "manual")
DEFAULT_CONFIDENCE_FLOOR = 0.8

# Sections a sub-agent may never propose writes to: external effects go through the
# approval queue, and meta/manager markers are the runtime's own bookkeeping.
PROTECTED_SECTIONS = frozenset({"action_queue", "meta", "manager_markers"})


class RegistryError(ValueError):
    """Base class for registry refusals."""


class UnknownAgent(RegistryError):
    def __init__(self, agent_id: str, known: list[str] | None = None):
        known = known or []
        hint = f" المعروف: {', '.join(sorted(known))}" if known else ""
        super().__init__(f"لا يوجد وكيل مسجّل بالمعرّف {agent_id}.{hint}")


class UnknownCapability(RegistryError):
    def __init__(self, capability: str, owners_by_capability: dict[str, str] | None = None):
        seen = sorted(owners_by_capability or {})
        hint = f" القدرات المتاحة: {', '.join(seen[:12])}" if seen else ""
        super().__init__(
            f"لا يوجد وكيل يعلن القدرة «{capability}».{hint} "
            "لا تخترع اسم وكيل ولا تفترض قدرة غير مسجّلة — اقترح إنشاء وكيل."
        )


class CapabilityConflict(RegistryError):
    def __init__(self, capability: str, owner: str):
        super().__init__(
            f"القدرة «{capability}» مملوكة مسبقًا للوكيل {owner}. "
            f"الملكية واحدة لكل قدرة: إما reassign_from='{owner}' صراحةً، أو افصل القدرتين "
            "بفعلين مختلفين (draft_x مقابل review_x)."
        )


class CapabilityMismatch(RegistryError):
    def __init__(self, agent_id: str, capability: str, declared: list[str]):
        super().__init__(
            f"الوكيل {agent_id} لا يعلن القدرة «{capability}». "
            f"المعلن: {', '.join(declared) or '—'}"
        )


# --------------------------------------------------------------------------- validation
def validate_capability(capability: str) -> str | None:
    """Return an error message, or None when the capability is well-formed."""
    value = str(capability or "")
    if not value:
        return "قدرة فارغة"
    if not CAPABILITY_RE.match(value):
        return (
            f"«{value}» ليست snake_case ASCII — القدرات الموصوفة نصًّا (§clinical documentation) "
            "هي السبب الجذري لتشابه المطابقة"
        )
    head = value.split("_", 1)[0]
    if head not in ACTION_PREFIXES:
        return (
            f"«{value}» تبدأ باسم مجال لا بفعل. استخدم فعلًا مثل "
            f"{', '.join(sorted(ACTION_PREFIXES)[:6])} … (مثال: draft_ops_directive)"
        )
    return None


def validate_input_schema(schema) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict) or not schema:
        return ["input_schema مفقود أو ليس كائنًا"]
    for key in schema:
        if key not in INPUT_SCHEMA_KEYS:
            errors.append(f"مفتاح غير مدعوم في input_schema: {key}")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(x, str) and x for x in required):
        errors.append("input_schema.required يجب أن تكون قائمة أسماء غير فارغة")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        errors.append("input_schema.properties يجب أن تكون كائنًا")
    else:
        for name, kind in properties.items():
            if not isinstance(name, str) or not name:
                errors.append("اسم خاصية غير صالح في input_schema.properties")
            elif kind not in PROPERTY_TYPES:
                errors.append(f"نوع غير مدعوم للخاصية {name}: {kind} (المسموح: {', '.join(PROPERTY_TYPES)})")
        if isinstance(required, list):
            for name in required:
                if name not in properties:
                    errors.append(f"خاصية مطلوبة غير معرّفة: {name}")
    return errors


def validate_card(card) -> list[str]:
    """Full card validation. Registration is rejected on any error."""
    errors: list[str] = []
    if not isinstance(card, dict):
        return ["البطاقة ليست كائنًا"]

    agent_id = str(card.get("agent_id") or "")
    if not AGENT_ID_RE.match(agent_id):
        errors.append(f"agent_id غير صالح: {agent_id!r} (المتوقع مثل AG-MORNING)")

    for field in ("name", "role"):
        if not str(card.get(field) or "").strip():
            errors.append(f"{field} مطلوب")

    capabilities = card.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append("capabilities مطلوبة ولا يمكن أن تكون فارغة")
    else:
        seen = set()
        for capability in capabilities:
            message = validate_capability(capability)
            if message:
                errors.append(message)
            elif capability in seen:
                errors.append(f"قدرة مكررة داخل البطاقة: {capability}")
            seen.add(capability)

    errors.extend(validate_input_schema(card.get("input_schema")))

    floor = card.get("confidence_floor")
    if floor is None:
        errors.append("confidence_floor مطلوب (0–1)")
    elif not isinstance(floor, (int, float)) or isinstance(floor, bool) or not 0 <= float(floor) <= 1:
        errors.append(f"confidence_floor خارج النطاق 0–1: {floor!r}")

    if card.get("cost_class") not in COST_CLASSES:
        errors.append(f"cost_class يجب أن يكون أحد: {', '.join(COST_CLASSES)}")

    status = card.get("status", "active")
    if status not in STATUSES:
        errors.append(f"status يجب أن يكون أحد: {', '.join(STATUSES)}")

    invoked_by = card.get("invoked_by", "manual")
    if invoked_by not in INVOKED_BY:
        errors.append(f"invoked_by يجب أن يكون أحد: {', '.join(INVOKED_BY)}")

    return errors


def normalize_card(card: dict) -> dict:
    """Fill defaults without inventing capabilities (never guesses what an agent can do)."""
    normalized = dict(card)
    normalized["status"] = card.get("status", "active")
    normalized["invoked_by"] = card.get("invoked_by", "manual")
    normalized["confidence_floor"] = float(card.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR))
    normalized["cost_class"] = card.get("cost_class", "medium")
    normalized["version"] = str(card.get("version", "1.0"))
    normalized["input_schema"] = {
        "required": list(card.get("input_schema", {}).get("required", [])),
        "properties": dict(card.get("input_schema", {}).get("properties", {})),
    }
    normalized["capabilities"] = list(card.get("capabilities", []))
    return normalized


def validate_input(card: dict, payload) -> list[str]:
    """Check a dispatch payload against the card's declared input contract."""
    schema = card.get("input_schema") or {}
    if payload is None:
        return []
    if not isinstance(payload, dict):
        return ["payload ليس كائنًا"]
    errors = []
    properties = schema.get("properties") or {}
    for name in schema.get("required", []):
        value = payload.get(name)
        if value in (None, "", []):
            errors.append(f"حقل مطلوب ناقص: {name}")
    for name, value in payload.items():
        if name not in properties:
            errors.append(f"حقل غير معلن في input_schema: {name}")
            continue
        kind = properties[name]
        if value in (None, "", []):
            continue
        if kind == "int" and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"{name} يجب أن يكون int")
        elif kind == "float" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            errors.append(f"{name} يجب أن يكون float")
        elif kind == "bool" and not isinstance(value, bool):
            errors.append(f"{name} يجب أن يكون bool")
        elif kind == "list" and not isinstance(value, list):
            errors.append(f"{name} يجب أن يكون list")
        elif kind == "object" and not isinstance(value, dict):
            errors.append(f"{name} يجب أن يكون object")
        elif kind in ("string", "date") and not isinstance(value, str):
            errors.append(f"{name} يجب أن يكون نصًّا")
    return errors


# --------------------------------------------------------------------------- reads
def _store(store=None) -> Store:
    return store or Store()


def rows(store=None) -> list[dict]:
    return list(_store(store).rows_all().get(SECTION) or [])


def cards(store=None, *, status=None, capability=None) -> list[dict]:
    result = []
    for row in rows(store):
        if status is not None and row.get("status", "active") != status:
            continue
        if capability is not None and capability not in (row.get("capabilities") or []):
            continue
        result.append(row)
    return result


def is_card(row: dict) -> bool:
    """A row is a card only if it carries the machine-checkable fields.

    An empty capability list still counts as a card (an agent that reassigned all of its
    capabilities away is retired, not unregistered) — but registration requires a
    non-empty list, so a card can only become empty through an explicit reassignment.
    """
    return isinstance(row.get("capabilities"), list) and isinstance(row.get("input_schema"), dict)


def get_card(agent_id: str, store=None) -> dict:
    known = [r.get("agent_id") for r in cards(store) if r.get("agent_id")]
    for row in rows(store):
        if row.get("agent_id") == agent_id:
            if not is_card(row):
                raise RegistryError(
                    f"الوكيل {agent_id} مسجّل بلا بطاقة قدرات — شغّل: "
                    "python3 -m connectors.agent_registry upgrade"
                )
            return row
    raise UnknownAgent(agent_id, known)


def owners_by_capability(store=None, *, status="active") -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in rows(store):
        if row.get("status", "active") != status:
            continue
        for capability in row.get("capabilities") or []:
            mapping.setdefault(capability, row.get("agent_id", ""))
    return mapping


def owner_of(capability: str, store=None) -> str | None:
    return owners_by_capability(store).get(capability)


def resolve(capability: str, store=None) -> str:
    """Capability → agent_id, or UnknownCapability with the available list."""
    owner = owner_of(capability, store)
    if not owner:
        raise UnknownCapability(capability, owners_by_capability(store))
    return owner


def conflicts(card: dict, store=None) -> dict[str, str]:
    """capability → current owner, for capabilities this card does not already own."""
    agent_id = str(card.get("agent_id") or "")
    mapping = owners_by_capability(store)
    return {
        capability: mapping[capability]
        for capability in (card.get("capabilities") or [])
        if mapping.get(capability) and mapping[capability] != agent_id
    }


# --------------------------------------------------------------------------- writes
def register(card: dict, store=None, *, reassign_from: str | None = None) -> dict:
    """Register or update one card. Raises on invalid cards and capability conflicts.

    ``reassign_from`` must name the current owner explicitly when transferring a
    capability — implicit takeover is how ownership drifts.
    """
    errors = validate_card(card)
    if errors:
        raise RegistryError("بطاقة غير صالحة: " + "؛ ".join(errors))
    normalized = normalize_card(card)

    clashing = conflicts(normalized, store)
    if clashing and reassign_from is None:
        capability, owner = sorted(clashing.items())[0]
        raise CapabilityConflict(capability, owner)
    if reassign_from is not None:
        unexpected = {c: o for c, o in clashing.items() if o != reassign_from}
        if unexpected:
            capability, owner = sorted(unexpected.items())[0]
            raise CapabilityConflict(capability, owner)

    holder: dict = {}

    def mutate(state):
        section = state.setdefault(SECTION, [])
        if reassign_from is not None and clashing:
            for row in section:
                if row.get("agent_id") != reassign_from:
                    continue
                remaining = [c for c in (row.get("capabilities") or []) if c not in clashing]
                if remaining != (row.get("capabilities") or []):
                    row["capabilities"] = remaining
                    row["reassigned_at"] = _now()
                    if not remaining:
                        row["status"] = "retired"
                        row["status_note"] = (
                            f"أُعيدت كل قدراته إلى {normalized['agent_id']} — تقاعد تلقائي"
                        )
        for index, row in enumerate(section):
            if row.get("agent_id") != normalized["agent_id"]:
                continue
            merged = dict(row)
            merged.update(normalized)
            merged["registered_at"] = row.get("registered_at") or _now()
            merged["updated_at"] = _now()
            section[index] = merged
            holder.update(merged)
            return True, merged
        created = dict(normalized)
        created["registered_at"] = _now()
        created["updated_at"] = created["registered_at"]
        section.append(created)
        holder.update(created)
        return True, created

    result = _store(store).transaction(
        mutate, "agent_registry_register",
        agent_id=normalized["agent_id"], capabilities=normalized["capabilities"],
    )
    log_event("agent_registered", agent_id=normalized["agent_id"],
              capabilities=normalized["capabilities"], reassigned_from=reassign_from or "")
    return result or holder


def set_status(agent_id: str, status: str, store=None, *, note: str = "") -> dict:
    """Pause or retire an agent without deleting its history."""
    if status not in STATUSES:
        raise RegistryError(f"status يجب أن يكون أحد: {', '.join(STATUSES)}")
    holder: dict = {}

    def mutate(state):
        for row in state.setdefault(SECTION, []):
            if row.get("agent_id") != agent_id:
                continue
            if row.get("status", "active") == status:
                return False, row
            row["status"] = status
            row["status_note"] = note
            row["updated_at"] = _now()
            holder.update(row)
            return True, row
        raise UnknownAgent(agent_id, [r.get("agent_id") for r in state.get(SECTION, [])])

    result = _store(store).transaction(mutate, "agent_registry_status",
                                       agent_id=agent_id, status=status)
    return result or holder


def _now() -> str:
    import datetime as dt
    return dt.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- seed / drift
# Capabilities derived from what these agents actually do today: JOB_SPECS wiring for
# the four scheduled agents, and the model roles used by delegation/council/mission.
SEED_CARDS = [
    {
        "agent_id": "AG-MORNING", "name": "Morning Briefing Agent",
        "role": "فرز الصباح ونبض العيادات وتنسيق أولويات اليوم",
        "capabilities": ["render_morning_brief", "schedule_focus_block",
                         "detect_day_conflicts", "archive_context_snapshot"],
        "input_schema": {"required": ["date"],
                         "properties": {"date": "date", "state_version": "int"}},
        "confidence_floor": 0.8, "cost_class": "low", "invoked_by": "scheduler",
        "version": "1.0",
    },
    {
        "agent_id": "AG-CLINICAL", "name": "Clinical & Ops Agent",
        "role": "متابعة تدريب DHS وحصر العهد ومتابعة محاضر المشرفين",
        "capabilities": ["track_supervisor_close", "track_dhs_training",
                         "draft_ops_directive", "report_section_kpis"],
        "input_schema": {"required": ["period"],
                         "properties": {"period": "string", "unit": "string",
                                        "state_version": "int"}},
        "confidence_floor": 0.85, "cost_class": "medium", "invoked_by": "scheduler",
        "version": "1.0",
    },
    {
        "agent_id": "AG-KNOWLEDGE", "name": "Knowledge & Audio Agent",
        "role": "تفريغ قنوات اليوتيوب التخصصية والكتب وتلخيصها (صوت + خريطة ذهنية)",
        "capabilities": ["digest_source_material", "summarize_audio_digest",
                         "render_weekly_mindmap"],
        "input_schema": {"required": ["source_ref"],
                         "properties": {"source_ref": "string", "target_minutes": "int",
                                        "state_version": "int"}},
        "confidence_floor": 0.75, "cost_class": "medium", "invoked_by": "scheduler",
        "version": "1.0",
    },
    {
        "agent_id": "AG-FINANCE", "name": "Finance & Life Agent",
        "role": "حوكمة الميزانية الشخصية وتفعيل الادخار وتوازن الأسرة",
        "capabilities": ["prepare_finance_review", "detect_budget_deviation",
                         "track_renewal_watch"],
        "input_schema": {"required": ["period"],
                         "properties": {"period": "string", "state_version": "int"}},
        "confidence_floor": 0.85, "cost_class": "low", "invoked_by": "scheduler",
        "version": "1.0",
    },
    # Reasoning roles actually dispatched by connectors/task_delegation.py today.
    {
        "agent_id": "AG-ROLE-MANAGER", "name": "Claude — Manager role",
        "role": "التخطيط والتوفيق بين مخرجات الوكلاء وصياغة النتيجة الإدارية",
        "capabilities": ["synthesize_mission_plan", "reconcile_specialist_findings",
                         "draft_executive_response"],
        "input_schema": {"required": ["objective"],
                         "properties": {"objective": "string", "cycle_id": "string",
                                        "state_version": "int"}},
        "confidence_floor": 0.8, "cost_class": "high", "invoked_by": "connector",
        "version": "1.0",
    },
    {
        "agent_id": "AG-ROLE-CRITIC", "name": "GPT — Critic role",
        "role": "التحقق من الادعاءات وتحدّي الافتراضات وكشف المخاطر",
        "capabilities": ["review_plan_risks", "verify_claims", "challenge_assumptions"],
        "input_schema": {"required": ["subject_ref"],
                         "properties": {"subject_ref": "string", "cycle_id": "string"}},
        "confidence_floor": 0.8, "cost_class": "medium", "invoked_by": "connector",
        "version": "1.0",
    },
    {
        "agent_id": "AG-ROLE-RESEARCHER", "name": "Gemini — Researcher role",
        "role": "مسح المصادر الخارجية واقتراح البدائل وتحديد فجوات الدليل",
        "capabilities": ["scan_external_sources", "propose_alternatives",
                         "identify_evidence_gaps"],
        "input_schema": {"required": ["question"],
                         "properties": {"question": "string", "cycle_id": "string"}},
        "confidence_floor": 0.75, "cost_class": "medium", "invoked_by": "connector",
        "version": "1.0",
    },
]


def upgrade(store=None, *, force: bool = False) -> dict:
    """Idempotently add capability cards to an existing install.

    Merge-if-missing: existing operational rows are extended, never overwritten, and
    nothing is deleted. ``force=True`` re-applies the seed values to card fields only.
    """
    store = _store(store)
    added, updated = [], []
    for seed in SEED_CARDS:
        existing = next((r for r in rows(store) if r.get("agent_id") == seed["agent_id"]), None)
        if existing is None:
            register(seed, store)
            added.append(seed["agent_id"])
            continue
        if is_card(existing) and not force:
            continue
        card = dict(seed)
        card.update({k: v for k, v in existing.items() if k not in seed or k in ("seq", "seed")})
        card["capabilities"] = seed["capabilities"]
        card["input_schema"] = seed["input_schema"]
        card["status"] = existing.get("status", "active")
        try:
            register(card, store)
            updated.append(seed["agent_id"])
        except CapabilityConflict:
            # Another agent already owns one of these capabilities — surface it as drift
            # instead of silently taking ownership.
            updated.append(seed["agent_id"] + ":CONFLICT")
    if added or updated:
        log_event("agent_registry_upgrade", added=added, updated=updated, force=force)
    return {"added": added, "updated": updated}


def drift(store=None, *, include_schedule: bool = True) -> list[str]:
    """Registry drift findings — the weekly-review check, runnable in CI."""
    findings: list[str] = []
    snapshot = rows(store)
    seen_capability: dict[str, str] = {}

    for row in snapshot:
        agent_id = str(row.get("agent_id") or "?")
        if not is_card(row):
            findings.append(f"{agent_id}: بلا بطاقة قدرات (capabilities/input_schema ناقصة)")
            continue
        for message in validate_card(row):
            findings.append(f"{agent_id}: {message}")
        if row.get("status", "active") != "active":
            continue
        for capability in row.get("capabilities") or []:
            if capability in seen_capability:
                findings.append(
                    f"قدرة مملوكة مرتين: {capability} → {seen_capability[capability]} و{agent_id}"
                )
            else:
                seen_capability[capability] = agent_id

    if include_schedule:
        try:
            from engine.scheduler import JOB_SPECS

            scheduled_agents = {job.get("agent") for job in JOB_SPECS}
            carded_agents = {r.get("agent_id") for r in snapshot if is_card(r)}
            for agent_id in sorted(scheduled_agents - carded_agents):
                findings.append(
                    f"{agent_id}: مُستدعى من المُجدول بلا بطاقة مسجّلة — أضف البطاقة "
                    "قبل أي إعادة تقسيم للوكلاء (JOB_SPECS[].agent)"
                )
            for card in snapshot:
                if card.get("invoked_by") == "scheduler" and card.get("agent_id") not in scheduled_agents:
                    findings.append(
                        f"{card.get('agent_id')}: معلَّم invoked_by=scheduler لكنه غير موجود في JOB_SPECS"
                    )
        except Exception as exc:  # noqa: BLE001 — الفحص لا يفشل بسبب غياب الجدولة
            findings.append(f"تعذّر فحص الجدول: {str(exc)[:120]}")
    return findings


def status_text(store=None) -> str:
    snapshot = cards(store)
    findings = drift(store)
    mapping = owners_by_capability(store)
    lines = [
        "🧭 Agent Registry — بطاقات القدرات (قسم sub_agents)",
        f"وكلاء مسجّلون: {len(snapshot)} | قدرات معلنة: {len(mapping)} | "
        f"انحرافات: {'لا شيء ✅' if not findings else str(len(findings)) + ' ⚠️'}",
    ]
    for row in snapshot:
        lines.append(
            f"   • {row.get('agent_id')} [{row.get('status', 'active')}/"
            f"{row.get('cost_class')}/≥{row.get('confidence_floor')}] — "
            + ", ".join(row.get("capabilities") or [])
        )
    for finding in findings:
        lines.append("   ⚠️ " + finding)
    return "\n".join(lines)


def main(argv=None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"

    if cmd in ("status", "list"):
        print(status_text())
        return 0
    if cmd == "capability":
        if len(args) < 2:
            print("اكتب اسم القدرة")
            return 2
        try:
            print(resolve(args[1]))
            return 0
        except UnknownCapability as exc:
            print(f"❌ {exc}")
            return 1
    if cmd == "check":
        findings = drift()
        print(status_text())
        if findings:
            print(f"\n❌ انحراف سجل الوكلاء: {len(findings)}")
            return 1
        print("\n✅ لا انحراف في سجل الوكلاء")
        return 0
    if cmd == "upgrade":
        result = upgrade(force="--force" in args)
        print(f"✅ أُضيف: {', '.join(result['added']) or '—'} | حُدّث: {', '.join(result['updated']) or '—'}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
