import unittest
from unittest.mock import patch

from connectors import clinical_sheet_knowledge as clinical


class _Execute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Values:
    def __init__(self, rows_by_tab):
        self.rows_by_tab = rows_by_tab

    def get(self, *, spreadsheetId, range):
        del spreadsheetId
        tab = range.split("'!")[0].lstrip("'")
        return _Execute({"values": self.rows_by_tab.get(tab, [])})


class _Spreadsheets:
    def __init__(self, rows_by_tab):
        self._values = _Values(rows_by_tab)

    def values(self):
        return self._values


class _Service:
    def __init__(self, rows_by_tab):
        self._spreadsheets = _Spreadsheets(rows_by_tab)

    def spreadsheets(self):
        return self._spreadsheets


def _rows():
    return {
        "Chronic_Disease_Somatic_Map": [
            list(clinical.TAB_SPECS["Chronic_Disease_Somatic_Map"]["headers"]),
            ["DIS-02", "آلام أسفل الظهر وعرق النسا", "فرضية ميكانيكية", "سائق حركي"],
        ],
        "Meditation_Protocols": [
            list(clinical.TAB_SPECS["Meditation_Protocols"]["headers"]),
            ["MED-01", "آلام الكتف", "تنفس هادئ"],
        ],
        "Clinical_Guidance_Engine": [
            list(clinical.TAB_SPECS["Clinical_Guidance_Engine"]["headers"]),
        ],
        "Keyword_Phrases_Bank": [
            list(clinical.TAB_SPECS["Keyword_Phrases_Bank"]["headers"]),
        ],
        "Symptoms_Psychological_Roots": [
            list(clinical.TAB_SPECS["Symptoms_Psychological_Roots"]["headers"]),
            ["SYM-07", "آلام أسفل الظهر", "رسالة نفسية مفترضة", "نمط سلوكي"],
        ],
    }


class ClinicalSheetKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.service = _Service(_rows())

    def test_search_returns_provenance_and_tab_policy(self):
        with patch.object(clinical, "_SERVICE", self.service):
            results = clinical.search("آلام أسفل الظهر")
        self.assertTrue(results)
        self.assertTrue(all(item["source_class"] == "CLINICAL_KNOWLEDGE" for item in results))
        self.assertTrue(all("source_ref" in item for item in results))
        psychosomatic = next(item for item in results if item["tab"] == "Symptoms_Psychological_Roots")
        self.assertEqual(psychosomatic["use"], "REFLECTION_ONLY_NOT_ETIOLOGY")

    def test_private_identifier_is_rejected_before_sheet_read(self):
        with patch.object(clinical, "_SERVICE", self.service):
            with self.assertRaisesRegex(ValueError, "أزل رقم الملف"):
                clinical.search("راجع المريض رقم الملف 12345 وآلام الظهر")

    def test_context_carries_non_causation_rules(self):
        with patch.object(clinical, "_SERVICE", self.service):
            context = clinical.compact_context("آلام أسفل الظهر")
        self.assertIn("GOVERNED CLINICAL SHEET EVIDENCE", context)
        self.assertIn("not diagnosis or proven etiology", context)
        self.assertIn("Do not imply that emotions caused cancer", context)

    def test_schema_mismatch_fails_closed(self):
        rows = _rows()
        rows["Meditation_Protocols"] = [["wrong", "headers"]]
        with patch.object(clinical, "_SERVICE", _Service(rows)):
            with self.assertRaisesRegex(RuntimeError, "schema mismatch"):
                clinical.search("آلام الكتف")


if __name__ == "__main__":
    unittest.main()

