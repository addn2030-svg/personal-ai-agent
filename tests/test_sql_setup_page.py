# -*- coding: utf-8 -*-
"""صفحة إعداد SQL: مولَّدة من ملفات SQL، ولا تتقادم بصمت.

الخطر الذي تحميه هذه الاختبارات: أن يُعدَّل `supabase/*.sql` (مثلًا لإصلاح أمني)
وتبقى الصفحة التي يلصقها المستخدم في Supabase تحمل المخطط القديم. لصق SQL قديم في
قاعدة بيانات حقيقية أسوأ من عدم اللصق — فيجب أن يفشل الفحص فورًا.
"""
import os
import re
import subprocess
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from scripts import make_sql_setup_page as page  # noqa: E402


class GeneratedFromSqlFiles(unittest.TestCase):
    def test_page_contains_every_sql_file_verbatim(self):
        """النص ليس مختصرًا ولا معاد كتابته: كل ملف كامل داخل الصفحة."""
        html_text = page.build()
        for meta in page.FILES:
            sql = page.read_sql(meta["file"])
            with self.subTest(file=meta["file"]):
                import html as html_module
                self.assertIn(html_module.escape(sql), html_text)

    def test_fingerprint_is_the_real_file_hash(self):
        import hashlib
        html_text = page.build()
        for meta in page.FILES:
            digest = hashlib.sha256(page.read_sql(meta["file"]).encode("utf-8")).hexdigest()
            self.assertIn(digest[:32], html_text, meta["file"])

    def test_html_escapes_prevent_tag_injection(self):
        """لو احتوى SQL على `<` لفسدت الصفحة — يجب أن يُهرَّب."""
        import html as html_module
        self.assertEqual(html_module.escape("<b>x</b>"), "&lt;b&gt;x&lt;/b&gt;")
        self.assertNotIn("<script>alert", page.build())

    def test_page_has_a_copy_box_per_file_plus_verify_and_smoke(self):
        html_text = page.build()
        self.assertEqual(html_text.count('textarea class="sql"'),
                         len(page.FILES) + 2)          # + التحقق + الاختبار الحي

    def test_verification_query_checks_every_created_object(self):
        """لولا هذا لمرّ التحقق وصفحة ناقصة: يجب أن يذكر كل جدول ودالة."""
        objects = ("state_snapshots", "tasks_mirror", "brain_episodes",
                   "brain_facts", "brain_working", "brain_norm", "brain_fold",
                   "brain_recall", "brain_stats", "brain_prune", "pg_trgm")
        for name in objects:
            self.assertIn(name, page.VERIFY_SQL, name)

    def test_verification_objects_actually_exist_in_the_sql_files(self):
        """لا نتحقق من شيء لم يُنشأ: أسماء الجداول والدوال مأخوذة من الملفات نفسها."""
        sql = "\n".join(page.read_sql(m["file"]) for m in page.FILES)
        for name in ("state_snapshots", "tasks_mirror", "brain_episodes",
                     "brain_facts", "brain_working", "brain_norm", "brain_fold",
                     "brain_recall", "brain_stats", "brain_prune"):
            self.assertIn(name, sql, name)

    def test_page_states_the_secret_key_rule(self):
        """الصفحة تُقرأ قبل أي إعداد — فيجب أن تحمل قاعدة عدم لصق المفاتيح."""
        self.assertIn("service_role", page.build())
        self.assertIn("لا تُلصق أي مفتاح", page.build())


class CommittedPageIsFresh(unittest.TestCase):
    def test_committed_page_matches_generated_output(self):
        if not os.path.exists(page.OUT):
            self.fail("الصفحة غير موجودة — شغّل: python3 scripts/make_sql_setup_page.py")
        with open(page.OUT, encoding="utf-8") as handle:
            committed = handle.read()
        self.assertEqual(
            committed, page.build(),
            "الصفحة قديمة بالنسبة لملفات SQL — أعد التوليد قبل الالتزام",
        )

    def test_check_mode_detects_staleness(self):
        """إثبات أن الفحص قادر على الفشل: أي تغيير في SQL يعني صفحة قديمة."""
        original_read = page.read_sql
        try:
            page.read_sql = lambda relative: original_read(relative) + "\n-- تغيير"
            with open(page.OUT, encoding="utf-8") as handle:
                committed = handle.read()
            self.assertNotEqual(page.build(), committed)
        finally:
            page.read_sql = original_read

    def test_cli_check_passes(self):
        result = subprocess.run(
            [sys.executable, os.path.join(BASE, "scripts", "make_sql_setup_page.py"), "--check"],
            cwd=BASE, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class PageInstructions(unittest.TestCase):
    def test_no_secret_value_is_embedded(self):
        """الصفحة تُفتح في المتصفح — لا يجوز أن تحمل أي مفتاح حقيقي."""
        html_text = page.build()
        for pattern in (r"sb_secret_[A-Za-z0-9]", r"eyJ[A-Za-z0-9_-]{10,}",
                        r"sb_publishable_[A-Za-z0-9]"):
            self.assertIsNone(re.search(pattern, html_text), pattern)

    def test_links_point_to_supabase_dashboard(self):
        self.assertIn("https://supabase.com/dashboard/new", page.build())
        self.assertIn("/sql/new", page.build())

    def test_pg_trgm_fallback_is_documented(self):
        html_text = page.build()
        self.assertIn("pg_trgm", html_text)
        self.assertIn("Extensions", html_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
