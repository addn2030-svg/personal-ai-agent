# -*- coding: utf-8 -*-
"""التحقق من صحة ملف النشر (render.yaml) — بلا مكتبات خارجية.

لماذا لا نكتفي بـ«الملف موجود»: ملف Blueprint تالف يُنتج في لوحة Render خطأ
غامضًا لا يفهمه إلا من كتب YAML، والمستخدم لا يجب أن يدفع ثمن خطأ إملائي.

لهذا نبني محلّل YAML مصغّرًا يفهم البنية المستخدمة فعلًا (خرائط متداخلة وقوائم
مسطّحة)، ونتحقق من:
1) أن الملف يُحلَّل بلا أخطاء، ولا يستخدم Tab في الإزاحة (YAML يمنعها).
2) أن الخدمة المعلنة تطابق ما يحتاجه هذا المشروع فعلًا (Dockerfile، /health).
3) أن كل متغير بيئة له قيمة أو `sync: false` (وإلا يمر متغير فارغ بصمت).
4) أن رايات استمرارية الحالة مفعّلة — بلا قرص دائم على الخطة المجانية.
5) **أن الملف لا يحتوي أي سرّ**: التحقق الأمني الأهم.
والأهم: اختبار ذاتي يثبت أن هذه الفحوص قادرة على الفشل أصلًا (لا اختبار أجوف).
"""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER_YAML = ROOT / "render.yaml"


# ------------------------------------------------------------ محلّل YAML مصغّر
class YamlSubsetError(ValueError):
    pass


def _clean(raw_lines):
    """يحذف التعليقات والفراغات، ويعيد (إزاحة، نص) — يرفض Tab في الإزاحة."""
    cleaned = []
    for number, raw in enumerate(raw_lines, start=1):
        if "\t" in raw:
            raise YamlSubsetError(f"سطر {number}: YAML يمنع Tab في الإزاحة")
        if raw.strip().startswith("#") or not raw.strip():
            continue
        body = raw.split(" #", 1)[0].rstrip()          # تعليق في نهاية السطر
        if not body.strip():
            continue
        indent = len(body) - len(body.lstrip(" "))
        cleaned.append((indent, body.strip(), number))
    return cleaned


def _scalar(text):
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if value in ("true", "false"):
        return value == "true"
    if value in ("null", "~"):
        return None
    return value


def parse_yaml_subset(text):
    lines = _clean(text.splitlines())

    def parse_block(index, indent):
        if index < len(lines) and lines[index][1].startswith("- "):
            result, index = [], index
            while index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
                item_text = lines[index][1][2:]
                if ":" in item_text:                    # عنصر قائمة هو خريطة
                    key, _, rest = item_text.partition(":")
                    item = {}
                    if rest.strip():
                        item[key.strip()] = _scalar(rest)
                    else:
                        nested, index = parse_block(index + 1, indent + 2)
                        item[key.strip()] = nested
                        result.append(item)
                        continue
                    # مفاتيح العنصر الشقيقة تبدأ بعد «- » أي بإزاحة +2 لا +4
                    extra, index = parse_block(index + 1, indent + 2)
                    if isinstance(extra, dict):
                        item.update(extra)
                    result.append(item)
                    continue
                result.append(_scalar(item_text))
                index += 1
            return result, index

        result = {}
        while index < len(lines) and lines[index][0] == indent:
            key, sep, rest = lines[index][1].partition(":")
            if not sep:
                raise YamlSubsetError(f"سطر {lines[index][2]}: توقّعنا «مفتاح: قيمة»")
            key = key.strip()
            if rest.strip():
                result[key] = _scalar(rest)
                index += 1
            else:
                child_indent = lines[index + 1][0] if index + 1 < len(lines) else indent
                nested, index = parse_block(index + 1, child_indent)
                result[key] = nested
        return result, index

    if not lines:
        raise YamlSubsetError("ملف فارغ")
    if lines[0][0] != 0:
        raise YamlSubsetError("أول مفتاح يجب أن يكون بلا إزاحة")
    document, _ = parse_block(0, 0)
    return document


# ------------------------------------------------------------------- الفحوص
class RenderBlueprintShapeTests(unittest.TestCase):
    def setUp(self):
        self.text = RENDER_YAML.read_text(encoding="utf-8")
        self.doc = parse_yaml_subset(self.text)
        self.service = self.doc["services"][0]

    def test_file_parses_and_defines_exactly_one_web_service(self):
        self.assertIn("services", self.doc)
        self.assertEqual(len(self.doc["services"]), 1,
                         "الخطة المجانية تمنح 750 ساعة لمساحة العمل كاملة — خدمة واحدة")
        self.assertEqual(self.service["type"], "web")
        self.assertEqual(self.service["plan"], "free")

    def test_build_and_health_match_the_repository(self):
        self.assertEqual(self.service["runtime"], "docker")
        self.assertTrue((ROOT / "Dockerfile").exists(), "runtime: docker بلا Dockerfile لا يُبنى")
        self.assertEqual(self.service["healthCheckPath"], "/health",
                         "Render ينتظر 200 من هذا المسار؛ /ready قد يُرجع 503")
        webhook = (ROOT / "connectors" / "telegram_webhook.py").read_text(encoding="utf-8")
        self.assertIn('self.path == "/health"', webhook)

    def test_dockerfile_runs_the_declared_entrypoint(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        last_cmd = [line for line in dockerfile.splitlines() if line.upper().startswith("CMD")]
        self.assertTrue(last_cmd, "Dockerfile بلا CMD")
        self.assertIn("telegram_webhook_runtime_memory", last_cmd[-1],
                      "نقطة الدخول التي اختبرها tests/test_production_entrypoint.py")

    def test_every_env_var_has_a_value_or_is_marked_for_the_dashboard(self):
        entries = self.service["envVars"]
        keys = [entry["key"] for entry in entries]
        self.assertEqual(len(keys), len(set(keys)), f"متغير مكرر: {keys}")
        for entry in entries:
            has_value = "value" in entry
            needs_dashboard = entry.get("sync") is False
            self.assertTrue(has_value or needs_dashboard,
                            f"{entry['key']} بلا قيمة وبلا sync: false — سيمر فارغًا بصمت")

    def test_secrets_are_never_hardcoded(self):
        """أهم فحص أمني: الملف يُدفع إلى Git، فلا سرّ فيه."""
        for entry in self.service["envVars"]:
            if entry.get("sync") is not False:
                continue
            self.assertNotIn("value", entry,
                             f"{entry['key']} يجب أن يُملأ في لوحة Render لا في Git")
        lowered = self.text.lower()
        for marker in ("sb_secret_", "sb_publishable_", "eyjhbgcioiji", "service_role_key: ",
                       "bot_token:", "api_key:", "-----begin"):
            self.assertNotIn(marker, lowered, f"أثر سرّ محتمل في render.yaml: {marker}")

    def test_state_persistence_is_enabled_for_a_diskless_host(self):
        values = {entry["key"]: entry.get("value") for entry in self.service["envVars"]}
        self.assertEqual(values.get("AI_OS_STATE_RESTORE_ON_BOOT"), "1",
                         "بلا قرص: الإقلاع يجب أن يستعيد آخر نسخة")
        self.assertEqual(values.get("AI_OS_STATE_PERSIST"), "1",
                         "بلا قرص: كل تغيير يجب أن يُدفع")
        self.assertEqual(values.get("SUPABASE_WRITE_ENABLED"), "1",
                         "الدفع يحتاج الكتابة مفعّلة")
        self.assertTrue(str(values.get("AI_OS_DATA_DIR", "")).startswith("/tmp"),
                        "على الخطة المجانية لا يوجد قرص دائم — نبني على /tmp بوعي")

    def test_automation_stays_gated_off_until_the_rollout_gate_passes(self):
        values = {entry["key"]: entry.get("value") for entry in self.service["envVars"]}
        self.assertEqual(values.get("SUPABASE_BACKUP_SCHEDULE_ENABLED"), "0",
                         "لا تُشغّل الأتمتة قبل تجاوز بوابة المرحلة (docs/supabase-rollout.md)")

    def test_docs_exist_and_are_linked_from_the_readme(self):
        doc = ROOT / "docs" / "free-hosting-migration.md"
        self.assertTrue(doc.exists())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/free-hosting-migration.md", readme)


class KeepWarmWorkflowTests(unittest.TestCase):
    """إبقاء الخدمة المجانية مستيقظة من داخل المستودع (بلا خدمة ثالثة).

    يُتحقق منه نصيًا لا بمحلّل YAML: الملف يستخدم block scalars (`run: |`)
    وهي خارج نطاق المحلّل المصغّر أعلاه. ويبقى الفحص الجذري في GitHub نفسه —
    ملف YAML تالف لا يظهر في قائمة Actions أصلًا.
    """

    WORKFLOW = ROOT / ".github" / "workflows" / "keep-warm.yml"

    def setUp(self):
        self.text = self.WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_exists_and_is_scheduled(self):
        self.assertTrue(self.WORKFLOW.exists())
        self.assertIn("schedule:", self.text)
        self.assertRegex(self.text, r'cron: "\*/10 ',
                         "كل 10 دقائق — أقل من مهلة النوم (15 دقيقة) بهامش")
        self.assertIn("workflow_dispatch", self.text,
                      "GitHub يوقف الجدولة في المستودعات الخاملة — التشغيل اليدوي يعيدها")

    def active_cron(self):
        """جدولة التنفيذ الفعلية — بلا أسطر التعليق (وإلا التقطنا مثال 24/7 في الشرح)."""
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            match = re.search(r'-\s*cron:\s*"(\S+ \S+ \S+ \S+ \S+)"', stripped)
            if match:
                return match.group(1)
        return None

    def test_pinging_24_7_would_exhaust_the_free_hours(self):
        """750 ساعة/شهر مقابل 744 لشهر كامل: الجدولة يجب أن تترك هامشًا."""
        cron = self.active_cron()
        self.assertIsNotNone(cron, "لا جدولة فعلية مفهومة")
        minutes, hours = cron.split()[:2]
        self.assertNotRegex(hours, r"^\*$",
                            "24/7 يستهلك 744 من 750 ساعة — اترك هامشًا أو وثّق التبديل")
        self.assertEqual(minutes, "*/10")

    def test_uses_health_not_ready(self):
        """/ready يُرجع 503 عند أي خلل في Google Sheets — فيفشل الإيقاظ بلا سبب."""
        self.assertIn("/health", self.text)
        self.assertNotIn("/ready", self.text)

    def test_url_comes_from_a_repo_variable_and_is_passed_via_env(self):
        """لا أسرار في المستودع، ولا حقن أوامر عبر نص المتغير."""
        self.assertIn("vars.RENDER_URL", self.text)
        self.assertIn("if: vars.RENDER_URL != ''", self.text,
                      "قبل ضبط المتغير يجب أن يتخطى العمل بهدوء لا أن يفشل")
        for line in self.text.splitlines():
            if "${{ vars.RENDER_URL }}" in line:
                self.assertTrue(line.strip().startswith("RENDER_URL:"),
                                f"يُمرَّر عبر env فقط، لا داخل نص الأوامر: {line.strip()}")
        self.assertNotIn("secrets.", self.text, "الإيقاظ لا يحتاج أي سرّ")

    def test_least_privilege_and_bounded_runtime(self):
        self.assertIn("permissions: {}", self.text,
                      "رمز المستودع لا يجب أن يمنح أي صلاحية لمجرد طلب HTTP")
        self.assertIn("timeout-minutes:", self.text)
        self.assertIn("--max-time", self.text, "الإقلاع البارد يحتاج مهلة أطول من المعتاد")

    def test_it_surfaces_an_unregistered_webhook(self):
        """خدمة تعمل وwebhook غير مسجَّل = بوت أخرس يبدو سليمًا."""
        self.assertIn('"configured": *false', self.text)
        self.assertIn("::warning", self.text)


class ParserSelfTest(unittest.TestCase):
    """يثبت أن الفحوص قادرة على الفشل — اختبار لا يفشل أبدًا لا قيمة له."""

    def test_parser_reads_the_real_file(self):
        doc = parse_yaml_subset(RENDER_YAML.read_text(encoding="utf-8"))
        self.assertIn("envVars", doc["services"][0])
        self.assertGreater(len(doc["services"][0]["envVars"]), 10)

    def test_parser_rejects_tabs(self):
        with self.assertRaises(YamlSubsetError):
            parse_yaml_subset("services:\n\t- type: web\n")

    def test_parser_rejects_a_line_without_a_colon(self):
        with self.assertRaises(YamlSubsetError):
            parse_yaml_subset("services:\n  just_text\n")

    def test_missing_sync_flag_would_be_caught(self):
        """نسخة معطوبة من الملف: متغير سرّي بلا قيمة وبلا sync — الفحص يمسكه."""
        broken = RENDER_YAML.read_text(encoding="utf-8").replace(
            "      - key: SUPABASE_URL\n        sync: false",
            "      - key: SUPABASE_URL")
        doc = parse_yaml_subset(broken)
        entry = next(e for e in doc["services"][0]["envVars"] if e["key"] == "SUPABASE_URL")
        self.assertNotIn("value", entry)
        self.assertNotEqual(entry.get("sync"), False, "هكذا يفشل فحص المتغيرات فعليًا")

    def test_persistence_flags_off_would_be_caught(self):
        broken = RENDER_YAML.read_text(encoding="utf-8").replace(
            '''      - key: AI_OS_STATE_RESTORE_ON_BOOT
        value: "1"''', '''      - key: AI_OS_STATE_RESTORE_ON_BOOT
        value: "0"''')
        values = {e["key"]: e.get("value")
                  for e in parse_yaml_subset(broken)["services"][0]["envVars"]}
        self.assertEqual(values["AI_OS_STATE_RESTORE_ON_BOOT"], "0", "الفحص يمسك الإطفاء")

    def test_a_real_secret_would_be_caught(self):
        broken = RENDER_YAML.read_text(encoding="utf-8").replace(
            "        sync: false            # المفتاح السري — خادم فقط، لا يدخل Git",
            "        value: sb_secret_abc123")
        self.assertIn("sb_secret_", broken.lower(),
                      "لو أضاف أحد سرًّا لالتقطه فحص test_secrets_are_never_hardcoded")


if __name__ == "__main__":
    unittest.main()
