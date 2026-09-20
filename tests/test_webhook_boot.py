# -*- coding: utf-8 -*-
"""إقلاع خدمة الـwebhook على استضافة حقيقية: لا سقوط، ولا صمت.

الحالة التي دفعت لهذه الاختبارات: عند غياب متغير واحد كان `run()` يرفع استثناءً
ويُسقط العملية. على Railway كان ذلك يعني حاوية تعيد التشغيل؛ وعلى Render يعني
**نشرًا يفشل** بلا نهاية، لأن فحص الصحة لا يجد خدمة تخدمه. الصحيح أن تُقلع
الخدمة، تُعلن العطل في /health، وتعيد المحاولة.
"""
import hashlib
import os
import tempfile
import unittest
from unittest import mock

from connectors import telegram_webhook as webhook


class PublicBaseUrlTests(unittest.TestCase):
    """اكتشاف الرابط العام — يلغي خطوة نسخ يدوي عند تغيير المنصة."""

    def test_explicit_variable_wins(self):
        env = {"TELEGRAM_WEBHOOK_BASE_URL": "https://mine.example.com/",
               "RENDER_EXTERNAL_HOSTNAME": "other.onrender.com"}
        self.assertEqual(webhook._resolve_public_base_url(env), "https://mine.example.com")

    def test_railway_domain_is_detected(self):
        env = {"RAILWAY_PUBLIC_DOMAIN": "bot.up.railway.app"}
        self.assertEqual(webhook._resolve_public_base_url(env), "https://bot.up.railway.app")

    def test_render_domain_is_detected(self):
        env = {"RENDER_EXTERNAL_HOSTNAME": "abdulrahman-ai-os.onrender.com"}
        self.assertEqual(webhook._resolve_public_base_url(env),
                         "https://abdulrahman-ai-os.onrender.com")

    def test_domain_already_carrying_a_scheme_is_not_doubled(self):
        env = {"RENDER_EXTERNAL_HOSTNAME": "https://x.onrender.com"}
        self.assertEqual(webhook._resolve_public_base_url(env), "https://x.onrender.com")

    def test_nothing_set_returns_empty(self):
        self.assertEqual(webhook._resolve_public_base_url({}), "")

    def test_blank_values_are_ignored(self):
        env = {"TELEGRAM_WEBHOOK_BASE_URL": "   ", "RAILWAY_PUBLIC_DOMAIN": ""}
        self.assertEqual(webhook._resolve_public_base_url(env), "")

    def test_explicit_wins_over_platform_even_when_blank(self):
        """المتغير الصريح الفارغ يجب ألّا يُسقط الالتقاط التلقائي للمنصة."""
        env = {"TELEGRAM_WEBHOOK_BASE_URL": "", "RENDER_EXTERNAL_HOSTNAME": "r.onrender.com"}
        self.assertEqual(webhook._resolve_public_base_url(env), "https://r.onrender.com")


class ConfigureWebhookTests(unittest.TestCase):
    """تسجيل الـwebhook: فشل مُعلَن، لا عملية مُسقَطة."""

    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(webhook, "_webhook_state",
                          {"configured": False, "error": "", "attempts": 0,
                           "permanent": False}).start()
        # السر يُشتق كسولًا فيُكتب في المتغير العام؛ نعزله حتى لا يتسرب بين الاختبارات
        mock.patch.object(webhook, "WEBHOOK_SECRET", "").start()

    def test_missing_token_does_not_raise_and_is_marked_permanent(self):
        with mock.patch.object(webhook.bot, "TOKEN", ""):
            result = webhook._configure_webhook()
        self.assertFalse(result)
        status = webhook.webhook_status()
        self.assertTrue(status["permanent"], "متغير ناقص عطل دائم لا يزول بإعادة المحاولة")
        self.assertIn("TELEGRAM_BOT_TOKEN", status["error"])

    def test_missing_public_url_is_reported_with_its_name(self):
        with mock.patch.object(webhook.bot, "TOKEN", "123:abc"), \
                mock.patch.object(webhook, "PUBLIC_BASE_URL", ""):
            self.assertFalse(webhook._configure_webhook())
        self.assertIn("TELEGRAM_WEBHOOK_BASE_URL", webhook.webhook_status()["error"])

    def test_transient_telegram_failure_is_not_permanent(self):
        with mock.patch.object(webhook.bot, "TOKEN", "123:abc"), \
                mock.patch.object(webhook, "PUBLIC_BASE_URL", "https://x.example.com"), \
                mock.patch.object(webhook, "_register_webhook",
                                  mock.Mock(side_effect=OSError("TLS EOF"))):
            self.assertFalse(webhook._configure_webhook())
        status = webhook.webhook_status()
        self.assertFalse(status["permanent"], "عطل شبكي يجب أن يُعاد سريعًا")
        self.assertIn("TLS EOF", status["error"])

    def test_success_records_state(self):
        with mock.patch.object(webhook.bot, "TOKEN", "123:abc"), \
                mock.patch.object(webhook, "PUBLIC_BASE_URL", "https://x.example.com"), \
                mock.patch.object(webhook, "_register_webhook", mock.Mock(return_value=None)):
            self.assertTrue(webhook._configure_webhook())
        status = webhook.webhook_status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["error"], "")

    def test_strict_mode_still_raises_for_scripts(self):
        """سلوك التشغيل اليدوي محفوظ: من يريد الفشل الصريح يحصل عليه."""
        with mock.patch.object(webhook.bot, "TOKEN", ""):
            with self.assertRaises(RuntimeError):
                webhook._configure_webhook(strict=True)

    def test_secret_is_derived_lazily_when_token_appears_later(self):
        """عطل صامت كان قائمًا: توكن يُضاف بعد الإقلاع لا يستطيع التسجيل أبدًا."""
        self.assertEqual(webhook.WEBHOOK_SECRET, "")
        with mock.patch.object(webhook.bot, "TOKEN", "999:later"), \
                mock.patch.object(webhook, "PUBLIC_BASE_URL", "https://x.example.com"), \
                mock.patch.object(webhook, "_register_webhook", mock.Mock()):
            self.assertTrue(webhook._configure_webhook())
        self.assertTrue(webhook.WEBHOOK_SECRET, "السر يجب أن يُشتق عند الحاجة")
        # ونفس القيمة يقرأها مدقّق الطلبات الواردة (وإلا رفض كل تحديث من تيليجرام)
        expected = hashlib.sha256(b"999:later:webhook").hexdigest()[:48]
        self.assertEqual(webhook.WEBHOOK_SECRET, expected)

    def test_explicit_secret_is_never_overwritten(self):
        """سر صريح من المستخدم يبقى كما هو — تحديث تيليجرام يفشل لو تغيّر تحته."""
        with mock.patch.object(webhook, "WEBHOOK_SECRET", "my-own-secret"), \
                mock.patch.object(webhook.bot, "TOKEN", "999:later"):
            webhook._ensure_webhook_secret()
            self.assertEqual(webhook.WEBHOOK_SECRET, "my-own-secret")

    def test_attempts_are_counted_for_diagnostics(self):
        with mock.patch.object(webhook.bot, "TOKEN", ""):
            for _ in range(3):
                webhook._configure_webhook()
        self.assertEqual(webhook.webhook_status()["attempts"], 3)


class HealthReportingTests(unittest.TestCase):
    """/health يجب أن يقول الحقيقة: خدمة حيّة + webhook غير مسجَّل."""

    def test_health_body_exposes_webhook_state(self):
        source = open("connectors/telegram_webhook.py", encoding="utf-8").read()
        self.assertIn('"telegram_webhook": webhook_status()', source,
                      "الفحص يجب أن يُظهر حالة الـwebhook لا أن يخفيها")
        self.assertNotIn('raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")', source,
                         "الرفع عند الإقلاع يعني حلقة إعادة تشغيل على الاستضافة")


class BootIntegrationTests(unittest.TestCase):
    """إقلاع كامل مع عمال خلفيين: الخدمة تخدم /health حتى بغياب الإعداد."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name}, clear=False).start()
        mock.patch.object(webhook, "_webhook_state",
                          {"configured": False, "error": "", "attempts": 0,
                           "permanent": False}).start()
        mock.patch.object(webhook, "WEBHOOK_SECRET", "").start()

    def test_run_survives_missing_config_and_starts_the_retry_worker(self):
        started = []
        with mock.patch.object(webhook.bot, "TOKEN", ""), \
                mock.patch.object(webhook, "_probe_sheets", mock.Mock(return_value=(False, "n/a"))), \
                mock.patch.object(webhook, "_start_calendar_alert_worker", mock.Mock()), \
                mock.patch.object(webhook.manager_fast_canary, "start_if_enabled", mock.Mock()), \
                mock.patch.object(webhook.proactive_worker, "start_if_enabled", mock.Mock()), \
                mock.patch.object(webhook, "ThreadingHTTPServer") as server, \
                mock.patch.object(webhook.threading, "Thread") as thread:
            def capture(**kwargs):
                started.append(kwargs.get("name"))
                return mock.Mock()
            thread.side_effect = capture
            # serve_forever لا يعود؛ نكتفي بأن الإقلاع وصل إلى الخادم
            server.return_value.serve_forever.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                webhook.run()
        self.assertIn("webhook-retry", started,
                      "بعد فشل التسجيل يجب أن توجد محاولة أخرى بلا إسقاط العملية")
        self.assertTrue(server.called, "الخادم يجب أن يُنشأ رغم غياب الإعداد")

    def test_run_does_not_start_retry_worker_on_success(self):
        started = []
        with mock.patch.object(webhook, "_configure_webhook", mock.Mock(return_value=True)), \
                mock.patch.object(webhook, "_probe_sheets", mock.Mock(return_value=(False, "n/a"))), \
                mock.patch.object(webhook, "_start_calendar_alert_worker", mock.Mock()), \
                mock.patch.object(webhook.manager_fast_canary, "start_if_enabled", mock.Mock()), \
                mock.patch.object(webhook.proactive_worker, "start_if_enabled", mock.Mock()), \
                mock.patch.object(webhook, "ThreadingHTTPServer") as server, \
                mock.patch.object(webhook.threading, "Thread") as thread:
            thread.side_effect = lambda **kw: started.append(kw.get("name")) or mock.Mock()
            server.return_value.serve_forever.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                webhook.run()
        self.assertNotIn("webhook-retry", started, "لا حاجة لمحاولات عند النجاح")


if __name__ == "__main__":
    unittest.main()
