# -*- coding: utf-8 -*-
"""Offline tests for the public/private knowledge boundary (v1.1.2).

The repo copy of the professional profile is portfolio-facing: contact fields
are sealed with [PUBLIC_REPO_REDACTED] and every byte of the public knowledge
tree must stay safe to read.  The live agent gets the real values from an
untracked `knowledge.private/` directory (or AI_OS_KNOWLEDGE_DIR), where text
is passed through unsanitized — masking applies only to the public copy.

Covers: no contact values in the tracked profile, redaction markers present,
profile_path() precedence (override → private dir → repo copy), masking on the
public copy, and non-masking on the private copy.
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

import agent_runtime  # noqa: E402

REDACTED = "[PUBLIC_REPO_REDACTED]"
PROFILE = "master-professional-profile.yaml"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?966|0)?\s*5\d[\s\d]{7,10}(?!\d)")
# نفس نمط _safe() — يتبع التنسيق بمسافات/شرطات (مثال: 966 50 000 0009)
SAUDI_PHONE_RE = re.compile(r"(?<![\dA-Za-z])(?:\+?966|0)[\s-]?5\d(?:[\s-]?\d){7,8}(?![\d])")

SAFE_EMAIL_SUFFIXES = (".iam.gserviceaccount.com", ".calendar.google.com")
SAFE_EMAIL_MARKS = ("example", "noreply@", "test@", "sample@")


# أرقام عرض مُدقَّقة يدويًا — لا قاعدة حدسية. الاختيار عمدًا: الفشل الآمن
# (الفشل على مثال بريء يكلّف سطرًا هنا) أفضل من النجاح الصامت على رقم حقيقي.
#  • +966 50 000 000{1..5} → سيناريوهات `engine/voice_call.py` demo A..E
#  • 0500000000           → نموذج اختبار التسليم في tests/test_commerce_agent.py
#  • +966 50 000 0009     → مثال التوثيق في README + نفس الرقم في test_commerce_agent
SYNTHETIC_NUMBERS = {
    "966500000001", "966500000002", "966500000003", "966500000004", "966500000005",
    "966500000009", "0500000000",
}


def _synthetic_number(raw):
    return re.sub(r"\D", "", raw) in SYNTHETIC_NUMBERS


def _profile_text():
    return Path(BASE, "knowledge", PROFILE).read_text(encoding="utf-8")


class PublicProfileIsSafe(unittest.TestCase):
    def test_contact_fields_exist_before_we_trust_their_seal(self):
        # إن تغيّرت بنية الملف فلا معنى لفحص الختم — نفشل بصوت عالٍ
        for key in ("email", "mobile"):
            self.assertIn(f"  {key}:\n", _profile_text(), f"حقل {key} مفقود من الملف")

    def test_contact_values_are_sealed(self):
        sealed = re.findall(r'  (?:email|mobile):\n    value: "([^"]*)"', _profile_text())
        self.assertEqual(sealed, [REDACTED, REDACTED], "حقل اتصال غير مختَّم")

    def test_allowlist_is_itself_demo_shaped(self):
        """كل رقم في قائمة الاستثناء يجب أن يكون بلا إنتروبيا (آلي التوليد)."""
        for num in SYNTHETIC_NUMBERS:
            body = re.sub(r"^0", "", num)
            body = re.sub(r"^966", "", body)
            self.assertLessEqual(len(set(body)), 3,
                                 f"استثناء مرفوض — قد يكون رقمًا حقيقيًا: …{body[-3:]}")
            self.assertLessEqual(len(set(re.sub(r"\d0*$", "", body))), 3)

    def test_saudi_phone_allowlist_is_closed_set(self):
        """المسار الوحيد لقبول رقم هو السجل أعلاه — لا نطاقات ولا أنماط حدسية."""
        self.assertNotIn("966500000000", SYNTHETIC_NUMBERS)
        self.assertFalse(_synthetic_number("+966 50 000 0010"),
                         "رقم خارج السجل وإن كان مجاورًا — يُرفض")
        self.assertFalse(_synthetic_number("0512345678"))

    def test_redaction_is_declared(self):
        self.assertEqual(_profile_text().count("redacted_for_public_repo: true"), 2)

    def test_no_raw_contact_patterns_in_profile(self):
        # service-account style emails are not personal contacts; they must not
        # appear in this file either.
        body = _profile_text()
        self.assertEqual([m.group(0) for m in EMAIL_RE.finditer(body)
                          if "iam.gserviceaccount.com" not in m.group(0)], [])
        for m in PHONE_RE.finditer(body):
            self.fail(f"نمط جوال ظاهر في النسخة العامة: {m.group(0)[:3]}…")
        self.assertEqual(body.count("privacy: PRIVATE_CONTACT"), 2,
                         "على الملف أن يظل يعلن تصنيف هذين الحقلين")

    def test_every_tracked_file_is_contact_free(self):
        """الحارس لا يكتفي بـ knowledge/: يفحص كل ملف متتبَّع في المستودع.

        مستثنيات موثّقة: معرّفات خدمة Google (عامة بطبيعتها)، نماذج الاختبار،
        وأرقام العرض متكررة الأرقام (`+966 50 000 0001`) في `engine/voice_call.py`
        — تُرفض بخاصية الإنتروبيا لا بمسار مُستثنى يدويًا، فلا يُفتح بابٌ لرقم حقيقي.
        """
        import subprocess
        files = subprocess.run(["git", "-C", BASE, "ls-files"],
                               capture_output=True, text=True).stdout.split()
        if not files:
            self.skipTest("git غير متاح في بيئة الاختبار")
        checked = 0
        for rel in files:
            if rel.endswith("test_knowledge_privacy.py"):
                continue  # يحمل أنماط الفحص نفسها
            text = Path(BASE, rel).read_text(encoding="utf-8", errors="ignore")
            checked += 1
            for m in EMAIL_RE.finditer(text):
                v = m.group(0)
                if v.endswith(SAFE_EMAIL_SUFFIXES) or any(k in v for k in SAFE_EMAIL_MARKS):
                    continue
                self.fail(f"{rel} يحمل بريدًا شخصيًا: {v[:4]}…")
            for m in SAUDI_PHONE_RE.finditer(text):
                if _synthetic_number(m.group(0)):
                    continue
                self.fail(f"{rel} يحمل رقم جوال غير تصنّعي: {m.group(0)[:4]}…")
        self.assertGreater(checked, 50, "لم يُفحص المستودع فعلًا")


class ProfilePathPrecedence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old_base = agent_runtime.BASE
        agent_runtime.BASE = self.root
        self.addCleanup(agent_runtime.__setattr__, "BASE", self._old_base)
        self._env = os.environ.pop("AI_OS_KNOWLEDGE_DIR", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.pop("AI_OS_KNOWLEDGE_DIR", None)
        if self._env is not None:
            os.environ["AI_OS_KNOWLEDGE_DIR"] = self._env

    def tearDown(self):
        self.tmp.cleanup()

    def test_falls_back_to_repo_copy(self):
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge" / PROFILE).write_text("x: 1\n", encoding="utf-8")
        self.assertEqual(agent_runtime.profile_path(),
                         self.root / "knowledge" / PROFILE)
        self.assertFalse(agent_runtime.profile_is_private())

    def test_private_dir_wins_over_repo_copy(self):
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge" / PROFILE).write_text("x: repo\n", encoding="utf-8")
        priv = self.root / "knowledge.private"
        priv.mkdir()
        (priv / PROFILE).write_text("x: private\n", encoding="utf-8")
        got = agent_runtime.profile_path()
        self.assertEqual(got, priv / PROFILE)
        self.assertTrue(agent_runtime.profile_is_private(got))

    def test_env_override_wins_over_everything(self):
        priv = self.root / "elsewhere"
        priv.mkdir()
        (priv / PROFILE).write_text("x: override\n", encoding="utf-8")
        os.environ["AI_OS_KNOWLEDGE_DIR"] = str(priv)
        self.assertEqual(agent_runtime.profile_path(), priv / PROFILE)

    def test_missing_everywhere_returns_none_and_survives(self):
        self.assertIsNone(agent_runtime.profile_path())
        text, sources = agent_runtime._knowledge_context("ملفي المهني")
        self.assertIsInstance(text, str)
        self.assertNotIn(PROFILE, " ".join(sources))


class ContextMasking(unittest.TestCase):
    FAKE_EMAIL = "someone.real@example-domain.test"
    FAKE_PHONE = "+966 55 123 4567"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._old_base = agent_runtime.BASE
        agent_runtime.BASE = self.root
        self.addCleanup(agent_runtime.__setattr__, "BASE", self._old_base)
        self._env = os.environ.pop("AI_OS_KNOWLEDGE_DIR", None)
        self.addCleanup(self._restore_env)
        body = ("identity:\n"
                f"  email:\n    value: \"{self.FAKE_EMAIL}\"\n"
                f"  mobile:\n    value: \"{self.FAKE_PHONE}\"\n")
        self.priv = self.root / "knowledge.private"
        self.priv.mkdir()
        (self.priv / PROFILE).write_text(body, encoding="utf-8")

    def _restore_env(self):
        os.environ.pop("AI_OS_KNOWLEDGE_DIR", None)
        if self._env is not None:
            os.environ["AI_OS_KNOWLEDGE_DIR"] = self._env

    def tearDown(self):
        self.tmp.cleanup()

    def test_private_copy_is_not_masked(self):
        text, sources = agent_runtime._knowledge_context("email mobile value")
        self.assertIn(self.FAKE_EMAIL, text, "المصدر الخاص يفترض أن يصل كما هو")
        self.assertIn(self.FAKE_PHONE, text)
        self.assertTrue(any("knowledge.private" in s for s in sources), sources)

    def test_private_copy_is_not_duplicated_by_public_scan(self):
        """knowledge/ يمسح الشجرة أيضًا — النسخة العامة يجب ألا تُحقن خلف الخاصة."""
        pub = self.root / "knowledge"
        pub.mkdir()
        (pub / PROFILE).write_text("identity:\n  dup: yes\n", encoding="utf-8")
        text, sources = agent_runtime._knowledge_context("email mobile value")
        self.assertEqual(len(sources), 1, f"مصادر مكرّرة: {sources}")
        self.assertNotIn("dup: yes", text, "تسرّبت النسخة العامة إلى السياق")

    def test_public_copy_is_masked(self):
        pub = self.root / "knowledge"
        pub.mkdir()
        (pub / PROFILE).write_text((self.priv / PROFILE).read_text(encoding="utf-8"),
                                  encoding="utf-8")
        # بدون المجلد الخاص → تُقرأ النسخة العامة وتُكمَّم
        import shutil
        shutil.rmtree(self.priv)
        text, sources = agent_runtime._knowledge_context("email mobile value")
        self.assertNotIn(self.FAKE_EMAIL, text, "النسخة العامة يجب أن تُكمَّم")
        self.assertIn("[PRIVATE_EMAIL]", text)
        self.assertIn("[PRIVATE_PHONE]", text)
        self.assertTrue(any(s.startswith("knowledge/") for s in sources), sources)


if __name__ == "__main__":
    unittest.main()
