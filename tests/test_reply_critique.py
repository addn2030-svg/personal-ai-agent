# -*- coding: utf-8 -*-
"""اختبارات النقد الذاتي قبل الإرسال — بلا شبكة وبلا نموذج.

ما نحميه:
1. **لا يُسقط الرد أبدًا**: أي خطأ ⇒ النص كما هو (الحارس الذي يُسقط الرد أسوأ من غيابه).
2. **لا يُغيّر المعنى**: الإضافات نص ثابت أو تنقية معرّف، ولا إعادة كتابة.
3. **الثلاث قواعد تُفرض**: إخلاء سريري · حجب معرّفات · تنبيه «لا إيصال».
4. **لا إيجابيات كاذبة** على ردود سليمة (وهذا ما يمنع الإزعاج اليومي).
5. قابل للإطفاء، ومسجَّل في التدقيق عند أي تعديل.
"""
import os
import unittest
from unittest import mock

from connectors import reply_critique as rc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CritiqueTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def clean(self, text, **kwargs):
        return rc.review(text, **kwargs)


# ------------------------------------------------------- 1) فشل لا يُسقط الرد
class FailOpen(CritiqueTestCase):
    def test_internal_error_returns_the_text_unchanged(self):
        with mock.patch.object(rc, "review", side_effect=RuntimeError("boom")):
            verdict = rc.review_and_amend("رد عادي", question="سؤال")
        self.assertEqual(verdict.text, "رد عادي")
        self.assertFalse(verdict.amended)

    def test_empty_text_is_returned_as_is(self):
        self.assertEqual(rc.review_and_amend("").text, "")

    def test_none_text_does_not_raise(self):
        self.assertEqual(rc.review_and_amend(None).text, "")

    def test_disabled_by_flag(self):
        with mock.patch.dict(os.environ, {"AI_REPLY_CRITIQUE": "0"}, clear=True):
            verdict = rc.review_and_amend("تم إرسال الرسالة إلى العميل")
        self.assertFalse(verdict.amended)
        self.assertIn("تم إرسال", verdict.text)

    def test_enabled_by_default(self):
        self.assertTrue(rc.enabled())


# ---------------------------------------------------- 2) حجب المعرّفات الخاصة
class PrivateIdentifierRedaction(CritiqueTestCase):
    def test_email_is_redacted(self):
        verdict = self.clean("تواصل معه على ahmed@example.com غدًا")
        self.assertNotIn("ahmed@example.com", verdict.text)
        self.assertIn("private_identifiers", verdict.violations)

    def test_saudi_mobile_is_redacted(self):
        for number in ("0555123456", "+966555123456", "966555123456"):
            verdict = self.clean(f"رقم العميل {number} محفوظ")
            self.assertNotIn(number, verdict.text, number)
            self.assertIn("private_identifiers", verdict.violations)

    def test_mrn_is_redacted(self):
        verdict = self.clean("رقم الملف: A-99213 — يحتاج مراجعة")
        self.assertNotIn("A-99213", verdict.text)
        self.assertIn("private_identifiers", verdict.violations)

    def test_clean_text_is_untouched(self):
        text = "أنجزنا مراجعة الخطة، والخطوة التالية إرسال المسودة."
        self.assertEqual(self.clean(text).text, text)


# ------------------------------------------------------ 3) إخلاء المسؤولية السريري
class ClinicalDisclaimer(CritiqueTestCase):
    def test_clinical_answer_without_disclaimer_gets_one(self):
        verdict = self.clean(
            "التمرين المناسب هو تمديد العضلة 3 مرات يوميًا",
            question="ما التمرين المناسب لمريض ألم أسفل الظهر؟",
        )
        self.assertIn("clinical_without_disclaimer", verdict.violations)
        self.assertIn("مراجعة مختص", verdict.text)

    def test_clinical_category_without_keywords_still_counts(self):
        verdict = self.clean("الجرعة المقترحة كذا", question="سؤال عام",
                             category="CLINICAL_PRIVATE")
        self.assertIn("clinical_without_disclaimer", verdict.violations)

    def test_existing_disclaimer_is_not_duplicated(self):
        text = ("التمرين كذا.\n\nملاحظة: القرار السريري النهائي يحتاج مراجعة مختص.")
        verdict = self.clean(text, question="تمرين لمريض؟")
        self.assertNotIn("clinical_without_disclaimer", verdict.violations)
        self.assertEqual(verdict.text.count("مراجعة مختص"), 1)

    def test_non_clinical_answer_is_not_annotated(self):
        verdict = self.clean("أرسل التقرير الأسبوعي قبل الخميس", question="ماذا أفعل غدًا؟")
        self.assertNotIn("clinical_without_disclaimer", verdict.violations)


# ------------------------------------------------ 4) ادّعاء تنفيذ بلا إيصال
class UnverifiedExecutionClaims(CritiqueTestCase):
    def test_claim_without_receipt_is_flagged(self):
        verdict = self.clean("تم إرسال الملخص إلى فريق التأهيل")
        self.assertIn("unverified_execution_claim", verdict.violations)
        self.assertIn("إيصال", verdict.text)

    def test_claim_with_receipt_is_left_alone(self):
        text = "أرسلت الملخص — Event ID: 4821 وتم تسجيله في سجل التدقيق"
        verdict = self.clean(text)
        self.assertNotIn("unverified_execution_claim", verdict.violations)

    def test_pending_approval_wording_is_not_a_claim(self):
        text = "جهزت مسودة بانتظار الموافقة، وسيُنفَّذ بعد اعتمادك."
        verdict = self.clean(text)
        self.assertNotIn("unverified_execution_claim", verdict.violations)

    def test_ordinary_answer_is_not_flagged(self):
        text = "الخطوة التالية أن نرسل الملخص بعد مراجعتك للمسودة."
        self.assertNotIn("unverified_execution_claim", self.clean(text).violations)


# ------------------------------------------------------------- 5) التكامل والتدقيق
class WiringAndAudit(CritiqueTestCase):
    def test_amendments_are_logged_to_the_audit_trail(self):
        events = []

        def fake_log(event, **details):
            events.append((event, details))

        import store  # noqa: E402  (engine/ على المسار داخل التطبيق)
        with mock.patch.object(store, "log_event", fake_log):
            rc.review_and_amend("تم إرسال التقرير", question="أرسل التقرير",
                                chat_id="123")
        self.assertTrue(events, "التعديل لم يُسجَّل في التدقيق")
        self.assertEqual(events[0][0], "REPLY_CRITIQUE_AMENDED")
        self.assertIn("unverified_execution_claim", events[0][1]["violations"])

    def test_clean_reply_logs_nothing(self):
        events = []
        import store  # noqa: E402
        with mock.patch.object(store, "log_event",
                               lambda e, **k: events.append(e)):
            rc.review_and_amend("كل شيء جاهز.", question="هل أنت جاهز؟")
        self.assertEqual(events, [])

    def test_reply_path_calls_the_critique_before_send(self):
        """الربط في المسار الرئيسي — بدونه الوحدة موجودة ولا تفعل شيئًا."""
        source = open(os.path.join(ROOT, "connectors", "telegram_bot_legacy.py"),
                      encoding="utf-8").read()
        self.assertIn("reply_critique.review_and_amend", source)
        # ويجري **قبل** الإرسال: أي بعد بناء الرد وقبل send.
        self.assertLess(source.index("reply_critique.review_and_amend"),
                        source.index("send(chat_id, answer + video_note)"))

    def test_wiring_is_defensive_so_a_broken_guard_cannot_drop_the_reply(self):
        """الحارس ليس أهم من الرسالة: فشل تحميله يمرّ بصمت لا يسقط الرد."""
        source = open(os.path.join(ROOT, "connectors", "telegram_bot_legacy.py"),
                      encoding="utf-8").read()
        self.assertIn("Reply critique unavailable", source)

    def test_cli_prints_the_amended_text(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(rc.main(["--clinical", "جرعة الدواء كذا"]), 0)
        self.assertIn("مراجعة مختص", buffer.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
