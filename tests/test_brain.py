# -*- coding: utf-8 -*-
"""اختبارات الدماغ الدائم — بلا شبكة إطلاقًا (عميل مُستبدَل).

ما نحميه هنا (كل بند قابل للكسر بصمت لو غاب الاختبار):
1. **الخمول الافتراضي**: بلا رايات لا نداء شبكة — لا تُرسل بيانات شخصية
   إلى السحابة لمجرد أن المفاتيح موجودة.
2. **البوابة المزدوجة للكتابة**: مفتاح سري + SUPABASE_WRITE_ENABLED + BRAIN_WRITE_ENABLED.
3. **البيانات السريرية لا تُرسَل أبدًا** — تُكتب محليًا وتُتخطّى المرآة.
4. **السقوط الآمن**: أي خطأ شبكة يعود بالنتيجة المحلية، ولا يُسقط الرد.
5. **عدم تسرّب المفاتيح** في رسائل الخطأ.
6. **احترام AI_OS_DATA_DIR** — الخلل الذي كان يوزّع الذاكرة على مجلدين على
   مضيف بلا قرص دائم.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from connectors import brain
from connectors.supabase_client import SupabaseError

ROOT = Path(__file__).resolve().parents[1]

SUPABASE_ENV = {
    "SUPABASE_URL": "https://demo1234.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test_key_0123456789",
    "SUPABASE_WRITE_ENABLED": "1",
}
BRAIN_ON = {"BRAIN_ENABLED": "1", "BRAIN_RECALL_ENABLED": "1", "BRAIN_WRITE_ENABLED": "1"}


def fake_client(*, rows=None, error=None, stats=None):
    """عميل Supabase وهمي — يسجّل كل نداء بدل تنفيذه."""
    rpc = mock.Mock(side_effect=error) if error else mock.Mock(return_value=rows if rows is not None else [])
    upsert = mock.Mock(side_effect=error) if error else mock.Mock(return_value=[])
    select = mock.Mock(return_value=[])
    return mock.Mock(rpc=rpc, upsert=upsert, select=select, insert=mock.Mock(return_value=[]),
                     stats=stats)


class BrainTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = {"AI_OS_DATA_DIR": self.tmp.name}
        patcher = mock.patch.dict(os.environ, base, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        # قاطع الدائرة حالة عامة — نصفّره لكل اختبار حتى لا يعتمد الترتيب على غيره.
        brain._reset_recall_breaker()

    def env(self, **extra):
        env = dict(os.environ)
        env.update(extra)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def memory_file(self, name):
        return Path(self.tmp.name) / "memory" / name


# --------------------------------------------------------- 1) الخمول الافتراضي
class DormantByDefault(BrainTestCase):
    def test_no_flags_means_no_network_and_local_only_recall(self):
        client = fake_client()
        result = brain.recall("العقد", client=client)
        client.rpc.assert_not_called()
        self.assertEqual(result.data["source"], "local")
        self.assertFalse(brain.capability().can_read)

    def test_capability_names_the_missing_flag(self):
        self.assertIn("BRAIN_ENABLED", brain.capability().problem)

    def test_status_text_says_dormant_without_lying_about_counts(self):
        text = brain.status_text()
        self.assertIn("خاملة", text)
        self.assertIn("BRAIN_ENABLED", text)

    def test_write_flags_alone_do_not_enable_cloud_writes(self):
        """مفاتيح Supabase مضبوطة + كتابة Supabase مفعّلة، لكن BRAIN_ENABLED مطفأ."""
        self.env(**SUPABASE_ENV)
        client = fake_client()
        outcome = brain.append_episode("note", "ملخّص طويل بما يكفي للتخزين", client=client)
        client.upsert.assert_not_called()
        self.assertTrue(outcome.ok)           # المحلي ينجح
        self.assertFalse(outcome.data["mirrored"])
        self.assertTrue(self.memory_file("episodic.jsonl").exists())


# ------------------------------------------------- 2) البوابة المزدوجة للكتابة
class WriteGating(BrainTestCase):
    def test_mirror_is_off_without_brain_write_flag(self):
        self.env(**SUPABASE_ENV, BRAIN_ENABLED="1", BRAIN_RECALL_ENABLED="1")
        client = fake_client()
        outcome = brain.append_episode("note", "ملخّص كافٍ", client=client)
        client.upsert.assert_not_called()
        self.assertFalse(outcome.data["mirrored"])

    def test_mirror_is_off_without_supabase_write_enabled(self):
        env = {k: v for k, v in SUPABASE_ENV.items() if k != "SUPABASE_WRITE_ENABLED"}
        self.env(**env, **BRAIN_ON)
        client = fake_client()
        outcome = brain.append_episode("note", "ملخّص كافٍ", client=client)
        client.upsert.assert_not_called()
        self.assertFalse(outcome.data["mirrored"])
        self.assertFalse(brain.capability().can_write)

    def test_mirror_is_off_with_a_publishable_key(self):
        """المفتاح العام لا يكتب أبدًا حتى لو فُعّلت كل الرايات."""
        env = dict(SUPABASE_ENV)
        env.update({"SUPABASE_SERVICE_ROLE_KEY": "sb_publishable_only_read_0123456789"})
        self.env(**env, **BRAIN_ON)
        self.assertFalse(brain.capability().can_write)

    def test_all_gates_open_mirrors_one_row(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        client = fake_client()
        outcome = brain.append_episode("decision", "تم اعتماد خطة التأهيل",
                                       chat_id="123", source_ref="audit:1", client=client)
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.data["mirrored"])
        client.upsert.assert_called_once()
        table, row = client.upsert.call_args.args[:2]
        self.assertEqual(table, "brain_episodes")
        self.assertEqual(row["chat_id"], "123")
        self.assertEqual(row["source_ref"], "audit:1")
        self.assertTrue(row["id"].startswith("EP-"))

    def test_fact_ids_collapse_identical_facts(self):
        """نفس (موضوع/علاقة/قيمة) ⇒ نفس المعرّف: upsert يمنع التكرار التراكمي."""
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        first = brain.remember_fact("المشروع", "الحالة", "قيد التنفيذ",
                                    source_ref="sheet:1", client=fake_client())
        second = brain.remember_fact("المشروع", "الحالة", "قيد التنفيذ",
                                     source_ref="sheet:2", client=fake_client())
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertTrue(first.data["id"].startswith("SM-"))
        # والقيمة المختلفة حقيقة أخرى بمعرّف آخر.
        third = brain.remember_fact("المشروع", "الحالة", "مكتمل", client=fake_client())
        self.assertNotEqual(first.data["id"], third.data["id"])


# --------------------------------------------- 3) المحتوى السريري يبقى محليًا
class SensitiveStaysLocal(BrainTestCase):
    def test_clinical_episode_is_written_locally_and_never_mirrored(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        client = fake_client()
        outcome = brain.append_episode("clinical", "مريض — ملاحظة سريرية",
                                       sensitivity="clinical_private", client=client)
        client.upsert.assert_not_called()
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.detail, "محلي فقط (حساس)")
        self.assertTrue(self.memory_file("episodic.jsonl").exists())

    def test_restricted_fact_is_never_mirrored(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        client = fake_client()
        outcome = brain.remember_fact("مريض", "تشخيص", "بيانات محمية",
                                      sensitivity="restricted", client=client)
        client.upsert.assert_not_called()
        self.assertFalse(outcome.data["mirrored"])

    def test_conversation_import_skips_clinical_private(self):
        state = {
            "meta": {"version": 1},
            "conversation_memory": [
                {"ts": "2026-09-20T10:00:00", "chat_id": "1", "role": "user",
                 "content": "ناقشنا مسودة العقد مع العمير", "category": "GENERAL"},
                {"ts": "2026-09-20T10:05:00", "chat_id": "1", "role": "user",
                 "content": "حالة المريض في الجلسة الثالثة", "category": "CLINICAL_PRIVATE"},
            ],
        }
        Path(self.tmp.name, "state.json").write_text(json.dumps(state, ensure_ascii=False),
                                                     encoding="utf-8")
        episodes = brain._conversation_episodes(limit=40)
        self.assertEqual(len(episodes), 1)
        self.assertIn("العقد", episodes[0]["summary"])


# ------------------------------------------------------------ 4) السقوط الآمن
class FailSoft(BrainTestCase):
    def test_recall_falls_back_to_local_on_supabase_error(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        client = fake_client(error=SupabaseError("boom", status=500))
        result = brain.recall("العقد", client=client)
        self.assertFalse(result.ok)
        self.assertEqual(result.data["source"], "local")
        self.assertTrue(result.error)

    def test_append_episode_reports_failure_without_raising(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        client = fake_client(error=SupabaseError("boom", status=500))
        outcome = brain.append_episode("note", "ملخّص كافٍ للتخزين", client=client)
        self.assertFalse(outcome.ok)
        self.assertFalse(outcome.data["mirrored"])
        self.assertTrue(self.memory_file("episodic.jsonl").exists())  # المحلي نُجّح

    def test_stats_reports_the_missing_table_hint(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        error = SupabaseError("relation does not exist", status=404,
                              code="42P01", hint="شغّل SQL الإعداد")
        result = brain.stats(client=fake_client(error=error))
        self.assertFalse(result.ok)
        self.assertIn("SQL", result.data.get("hint", ""))

    def test_agent_runtime_brain_context_never_raises(self):
        """مسار الرد لا يسقط مهما حدث في طبقة الذاكرة."""
        import sys
        sys.path.insert(0, str(ROOT / "engine"))
        import agent_runtime  # noqa: E402

        with mock.patch.object(brain, "recall_context", side_effect=RuntimeError("boom")):
            self.assertEqual(agent_runtime._brain_context("أي سؤال"), "")

    def test_recall_context_is_empty_when_recall_flag_is_off(self):
        self.env(**SUPABASE_ENV, BRAIN_ENABLED="1")
        self.assertEqual(brain.recall_context("العقد"), "")

    def test_breaker_opens_after_repeated_failures_and_spares_the_network(self):
        """سؤال المستخدم لا يدفع ثمن مهلة شبكة ميتة في كل مرة."""
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        failing = fake_client(error=SupabaseError("boom", status=500))
        for _ in range(brain.BREAKER_FAILURES):
            brain.recall("العقد", client=failing)
        fresh = fake_client(rows=[])
        result = brain.recall("العقد", client=fresh)
        fresh.rpc.assert_not_called()
        self.assertEqual(result.data["source"], "local")
        self.assertIn("قاطع", result.detail)

    def test_success_resets_the_breaker_counter(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        failing = fake_client(error=SupabaseError("boom", status=500))
        brain.recall("العقد", client=failing)
        brain.recall("العقد", client=fake_client(rows=[]))     # نجاح
        brain.recall("العقد", client=failing)                  # إخفاق واحد فقط بعد النجاح
        fresh = fake_client(rows=[])
        brain.recall("العقد", client=fresh)
        fresh.rpc.assert_called_once()                          # القاطع ما زال مغلقًا


# ------------------------------------------------------------- 5) عدم تسرّب المفاتيح
class NoSecretLeakage(BrainTestCase):
    def test_error_message_redacts_the_service_key(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        key = SUPABASE_ENV["SUPABASE_SERVICE_ROLE_KEY"]
        client = fake_client(error=SupabaseError(f"failed with key {key}", status=500))
        result = brain.recall("العقد", client=client)
        self.assertNotIn(key, result.error)

    def test_status_text_never_prints_a_key(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        text = brain.status_text()
        self.assertNotIn(SUPABASE_ENV["SUPABASE_SERVICE_ROLE_KEY"], text)


# ------------------------------------------------- 6) AI_OS_DATA_DIR والترحيل
class StorageLocation(BrainTestCase):
    def test_memory_dir_follows_ai_os_data_dir(self):
        """على Render المجاني هذا هو الفرق بين ذاكرة تنجو وذاكرة تُمحى."""
        self.assertEqual(brain.memory_dir(), os.path.join(self.tmp.name, "memory"))

    def test_engine_memory_module_follows_ai_os_data_dir(self):
        import sys
        sys.path.insert(0, str(ROOT / "engine"))
        import memory  # noqa: E402
        self.assertEqual(memory.MEM_DIR, os.path.join(self.tmp.name, "memory"))
        self.assertTrue(str(memory.EPISODIC).startswith(self.tmp.name))

    def test_engine_rag_index_follows_ai_os_data_dir(self):
        import sys
        sys.path.insert(0, str(ROOT / "engine"))
        import rag  # noqa: E402
        self.assertTrue(str(rag.INDEX).startswith(self.tmp.name))

    def test_import_local_migrates_jsonl_and_conversations(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        memory_dir = Path(self.tmp.name) / "memory"
        memory_dir.mkdir(parents=True)
        memory_dir.joinpath("episodic.jsonl").write_text(
            json.dumps({"id": "EP-1", "ts": "2026-09-19T08:00:00", "kind": "decision",
                        "summary": "اعتمدنا خطة الأسبوع", "refs": [], "sensitivity": "normal"},
                       ensure_ascii=False) + "\n"
            + json.dumps({"id": "EP-2", "ts": "2026-09-19T09:00:00", "kind": "clinical",
                          "summary": "ملاحظة سريرية", "sensitivity": "clinical_private"},
                         ensure_ascii=False) + "\n",
            encoding="utf-8")
        memory_dir.joinpath("semantic.jsonl").write_text(
            json.dumps({"id": "SM-1", "ts": "2026-09-19T10:00:00", "subject": "المشروع",
                        "predicate": "البداية", "value": "أكتوبر", "source_ref": "sheet:1",
                        "confidence": 0.9}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        Path(self.tmp.name, "state.json").write_text(json.dumps({
            "meta": {"version": 1},
            "conversation_memory": [{"ts": "2026-09-20T10:00:00", "chat_id": "1",
                                     "role": "user", "content": "ناقشنا مسودة العقد",
                                     "category": "GENERAL"}],
        }, ensure_ascii=False), encoding="utf-8")

        client = fake_client()
        report = brain.import_local(client=client)
        self.assertTrue(report.ok, report.error)
        self.assertEqual(report.data["episodes"], 1)      # السريري مُستبعَد
        self.assertEqual(report.data["facts"], 1)
        self.assertEqual(report.data["conversations"], 1)
        self.assertEqual(report.data["skipped_sensitive"], 1)
        self.assertEqual(report.data["pushed"], 3)

    def test_import_local_refuses_without_write_gate(self):
        self.env(**SUPABASE_ENV, BRAIN_ENABLED="1", BRAIN_RECALL_ENABLED="1")
        report = brain.import_local(client=fake_client())
        self.assertFalse(report.ok)


# ------------------------------------------------------- 7) الاسترجاع المنسَّق
class RecallFormatting(BrainTestCase):
    def test_recall_context_carries_provenance_for_every_line(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        rows = [{"item_type": "episode", "item_id": "EP-1",
                 "occurred_at": "2026-09-19T08:00:00+00:00", "title": "decision",
                 "snippet": "اعتمدنا خطة الأسبوع", "source_ref": "audit:7",
                 "sensitivity": "normal", "score": 3.5}]
        block = brain.recall_context("خطة الأسبوع", client=fake_client(rows=rows))
        self.assertIn("DURABLE BRAIN RECALL", block)
        self.assertIn("source_ref=audit:7", block)
        self.assertIn("اعتمدنا خطة الأسبوع", block)

    def test_recall_context_is_empty_when_there_is_nothing(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        self.assertEqual(brain.recall_context("لا شيء", client=fake_client(rows=[])), "")

    def test_recall_clamps_the_requested_limit(self):
        self.env(**SUPABASE_ENV, **BRAIN_ON)
        client = fake_client(rows=[])
        brain.recall("العقد", limit=10_000, client=client)
        self.assertEqual(client.rpc.call_args.args[1]["match_count"], brain.MAX_RECALL_LIMIT)

    def test_blank_episode_summary_is_rejected(self):
        outcome = brain.append_episode("note", "   ")
        self.assertFalse(outcome.ok)


# --------------------------------------------------- 8) تكامل الإعداد والنشر
class DeploymentWiring(BrainTestCase):
    def test_render_blueprint_enables_the_durable_brain(self):
        text = (ROOT / "render.yaml").read_text(encoding="utf-8")
        for key in ("BRAIN_ENABLED", "BRAIN_RECALL_ENABLED", "BRAIN_WRITE_ENABLED"):
            self.assertIn(key, text, f"{key} مفقود — الذاكرة ستضيع على مضيف بلا قرص")

    def test_sql_schema_is_shipped_and_uses_the_brain_tables(self):
        sql_path = ROOT / "supabase" / "03_brain_memory.sql"
        self.assertTrue(sql_path.exists())
        sql = sql_path.read_text(encoding="utf-8")
        for table in ("brain_episodes", "brain_facts", "brain_working"):
            self.assertIn(table, sql)
        self.assertIn("enable row level security", sql)
        self.assertIn("revoke all", sql)

    def test_brain_sql_is_reachable_from_the_connector_cli(self):
        self.assertIn("brain_episodes", brain.read_sql(brain.SQL_FILE))

    def test_gitignore_keeps_personal_memory_out_of_git(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/memory/", ignored,
                      "ملفات الذاكرة الشخصية يجب ألا تدخل Git أبدًا")

    def test_docs_exist_and_are_linked_from_the_readme(self):
        doc = ROOT / "docs" / "brain-durable-memory.md"
        self.assertTrue(doc.exists())
        self.assertIn("docs/brain-durable-memory.md",
                      (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_env_example_documents_the_brain_flags(self):
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in ("BRAIN_ENABLED", "BRAIN_RECALL_ENABLED", "BRAIN_WRITE_ENABLED"):
            self.assertIn(key, example)


if __name__ == "__main__":
    unittest.main(verbosity=2)
