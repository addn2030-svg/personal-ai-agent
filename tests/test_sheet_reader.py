# -*- coding: utf-8 -*-
"""قارئ xlsx القياسي + الترحيل الفعلي من الشيت إلى الحالة إلى الحمولة السحابية.

سبب وجود القارئ: `openpyxl` حزمة خارجية، و`engine/migrate.py` كان يتوقف بلاها —
فلا يمكن التحقق من الترحيل في بيئة لا تحملها. وهذه اختبارات تُثبت أن القراءة
صحيحة على ملف مصنوع بأيدينا، ثم على الشيت الحقيقي المتتبَّع في Git.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHEET = os.path.join(BASE, "data", "master-sheet.xlsx")
sys.path.insert(0, BASE)

from engine import sheet_reader  # noqa: E402

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# أوراق الشيت الحقيقي وعدد صفوف بياناتها (مقيسة من الملف نفسه)
EXPECTED_ROWS = {
    "مهام": 13, "مشاريع": 11, "عملاء وفرص": 8, "مؤشرات القسم": 30,
    "مواعيد": 4, "قرارات": 5, "متابعة مرضى": 6, "صندوق الصوت": 4,
    "تعلم": 5, "مالية": 8,
}


def build_book(path, sheets):
    """يبني ملف xlsx صغيرًا بأيدينا: نصوص مشتركة · inline · أرقام · تاريخ."""
    shared = ["العنوان", "الحالة", "نص مشترك", "التاريخ"]
    shared_xml = (f'<sst xmlns="{NS}" count="{len(shared)}" uniqueCount="{len(shared)}">'
                  + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
    styles = (f'<styleSheet xmlns="{NS}"><numFmts count="1">'
              f'<numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/></numFmts>'
              f'<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164"/></cellXfs></styleSheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/sharedStrings.xml", shared_xml)
        z.writestr("xl/styles.xml", styles)
        entries = []
        for index, (name, rows) in enumerate(sheets.items(), start=1):
            entries.append((name, f"rId{index}", f"xl/worksheets/sheet{index}.xml"))
            z.writestr(f"xl/worksheets/sheet{index}.xml", rows)
        sheet_tags = "".join(
            f'<sheet xmlns:r="{RELNS}" name="{name}" sheetId="{i}" r:id="{rid}"/>'
            for i, (name, rid, _) in enumerate(entries, start=1))
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{NS}"><sheets>{sheet_tags}</sheets></workbook>')
        rels = "".join(
            f'<Relationship Type=".../worksheet" Target="/{target}" Id="{rid}"/>'
            for _, rid, target in entries)
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')


def row_xml(index, cells):
    body = "".join(cells)
    return f'<row r="{index}">{body}</row>'


def cell(ref, value, kind=None, style=None):
    attrs = f'r="{ref}"' + (f' t="{kind}"' if kind else "") + (f' s="{style}"' if style is not None else "")
    if kind == "inlineStr":
        return f'<c {attrs}><is><t>{value}</t></is></c>'
    return f'<c {attrs}><v>{value}</v></c>'


class SyntheticWorkbook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "book.xlsx")
        body = (
            '<worksheet xmlns="%s"><sheetData>%s%s%s</sheetData></worksheet>' % (
                NS,
                row_xml(1, [cell("A1", 0, "s"), cell("B1", 1, "s")]),
                row_xml(2, [cell("A2", "نص مباشر", "inlineStr"), cell("B2", 45700, style=1)]),
                row_xml(3, [cell("A3", 2, "s"), cell("B3", "42")]),
            )
        )
        build_book(self.path, {"ورقة": body})

    def test_reads_shared_inline_numbers_and_dates(self):
        book = sheet_reader.load_workbook(self.path)
        sheet = book["ورقة"]
        self.assertEqual(sheet[1][0].value, "العنوان")
        self.assertEqual(sheet[1][1].value, "الحالة")
        self.assertEqual(sheet[2][0].value, "نص مباشر")
        self.assertEqual(sheet[3][0].value, "نص مشترك")
        self.assertEqual(sheet[3][1].value, 42)

    def test_date_cell_becomes_a_date_not_a_serial(self):
        value = sheet_reader.load_workbook(self.path)["ورقة"][2][1].value
        self.assertEqual(str(value), "2025-02-12")   # 45700 مرجع محسوب: 1899-12-30 + 45700

    def test_iter_rows_matches_openpyxl_signature(self):
        rows = list(sheet_reader.load_workbook(self.path)["ورقة"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(rows[0][0], "نص مباشر")

    def test_unknown_sheet_raises_with_available_names(self):
        with self.assertRaises(KeyError) as ctx:
            sheet_reader.load_workbook(self.path)["لا توجد"]
        self.assertIn("ورقة", str(ctx.exception))


@unittest.skipUnless(os.path.exists(SHEET), "الشيت الرئيسي غير موجود")
class RealMasterSheet(unittest.TestCase):
    """قراءة الشيت الحقيقي المتتبَّع في Git — أحد عشر ورقة و106 صفوف."""

    def setUp(self):
        self.book = sheet_reader.load_workbook(SHEET)

    def test_all_eleven_sheets_are_present(self):
        self.assertEqual(len(self.book.sheetnames), 11)
        self.assertIn("اقرأني", self.book.sheetnames)
        self.assertIn("متابعة مرضى", self.book.sheetnames)

    def test_row_counts_per_sheet(self):
        for name, expected in EXPECTED_ROWS.items():
            with self.subTest(sheet=name):
                self.assertEqual(self.book[name].max_row - 1, expected)

    def test_headers_are_readable_arabic(self):
        header = [c.value for c in self.book["مهام"][1]]
        self.assertEqual(header[:3], ["العنوان", "النوع", "الأولوية"])

    def test_dates_are_dates_not_numbers(self):
        row = self.book["متابعة مرضى"][2]                  # صف P-101
        self.assertEqual(row[0].value, "P-101")
        visit = row[2].value                               # «آخر زيارة» = عمود التاريخ
        self.assertRegex(str(visit), r"^\d{4}-\d{2}-\d{2}$")
        # مرجع مستقل: 46248 = 2026-08-14 (وليس 13 — كان خطأ الإزاحة)
        self.assertEqual(str(visit), "2026-08-14")


@unittest.skipUnless(os.path.exists(SHEET), "الشيت الرئيسي غير موجود")
class MigrationEndToEnd(unittest.TestCase):
    """الشيت → الحالة → الحمولة السحابية: السلسلة الكاملة التي تُستَخدم في SQL."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        env = dict(os.environ, AI_OS_DATA_DIR=cls.tmp)
        env.pop("SUPABASE_INCLUDE_CLINICAL", None)
        result = subprocess.run(
            [sys.executable, os.path.join(BASE, "engine", "migrate.py")],
            cwd=BASE, env=env, capture_output=True, text=True, timeout=120,
        )
        cls.result = result
        state_path = os.path.join(cls.tmp, "state.json")
        if os.path.exists(state_path):
            with open(state_path, encoding="utf-8") as handle:
                cls.state = json.load(handle)
        else:
            cls.state = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_migration_succeeds(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr[-500:])

    def test_ten_sections_and_ninety_four_rows(self):
        """94 = مجموع صفوف البيانات بلا ورقة «اقرأني» (دليل استخدام، لا بيانات)."""
        total = sum(len(self.state.get(key) or []) for key in (
            "tasks", "projects", "leads", "kpis", "meetings", "decisions",
            "followups", "voice", "learning", "finance"))
        self.assertEqual(total, 94)

    def test_waiting_for_is_derived(self):
        self.assertEqual(len(self.state["waiting_for"]), 5)

    def test_readme_sheet_is_not_imported(self):
        self.assertNotIn("اقرأني", json.dumps(self.state, ensure_ascii=False)[:1])

    def test_cloud_payload_hides_patients_but_keeps_operations(self):
        from connectors.cloud_payload import sanitize
        payload, report = sanitize(self.state)
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["followups"], [])
        self.assertEqual(report["withheld"]["followups"], 6)
        for code in ("P-101", "P-102", "P-103", "P-104", "P-105", "P-106"):
            self.assertNotIn(code, blob)
        self.assertNotIn("أحمد", blob)
        self.assertEqual(len(payload["kpis"]), 30)        # الإحصاء الإداري يبقى
        self.assertEqual(len(payload["tasks"]), 13)
        self.assertEqual(payload["meta"]["cloud_withheld"], "followups: 6")

    def test_snapshot_of_the_migrated_state_verifies(self):
        from connectors import supabase_state
        row = {**supabase_state.snapshot_from(self.state, reason="اختبار ترحيل"), "id": 1}
        self.assertTrue(supabase_state.verify_row(row)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
