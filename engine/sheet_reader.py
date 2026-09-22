# -*- coding: utf-8 -*-
"""قارئ xlsx بالمكتبة القياسية فقط — بديل `openpyxl` عند غيابه.

لماذا؟
-----
`engine/migrate.py` يقرأ `data/master-sheet.xlsx` (الشيت الرئيسي) عبر
`openpyxl`، وهذه حزمة خارجية. النتيجة أن الترحيل من الشيت **لا يعمل** في أي
بيئة لا تحملها — ولا يمكن التحقق منه محليًا، فيبقى بلا اختبار حقيقي.

الترحيل عملية تُنفَّذ مرة واحدة على بيانات حقيقية، واحتمال فشلها في صمت أسوأ من
كلفة قارئ صغير. xlsx أصلًا ملف zip يحوي XML — والقارئ هنا يحتاج 100 سطر.

الحدود (مقصودة):
- قراءة فقط (`data_only` مفروض) — لا كتابة، لا معادلات مُقيَّمة.
- الأنواع: نصوص · أرقام · تواريخ (Serial) · منطقي · نصوص مشتركة · inline.
- لا يدعم: الصور، التنسيق الشرطي، الجداول المحورية. لا حاجة لها هنا.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
import zipfile

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# أنماط التاريخ القياسية في Excel
_DATE_FORMAT_IDS = set(range(14, 23)) | set(range(45, 48)) | {27, 30, 36, 50, 57}
_EPOCH = dt.datetime(1899, 12, 30)
_DAY = dt.timedelta(days=1)


class Cell:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def _column_index(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference or "")
    index = 0
    for char in (letters.group(1) if letters else "A"):
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _serial_to_datetime(value: float):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number <= 0:
        return value
    moment = _EPOCH + _DAY * number
    # «عملاق» Excel: البرنامج يعتبر 1900-02-29 يومًا موجودًا (وهو غير موجود).
    # نقطة الأصل 1899-12-30 تحسب هذه الزيادة ضمنًا لما بعد 60، فيبقى التصحيح
    # لازمًا **للأرقام الأصغر من 60 فقط**. (الخطأ في الاتجاه المعاكس يُنتج
    # تواريخ بناقص يوم — وهو ما كشفه اختبار الشيت الحقيقي.)
    # مراجع مؤكَّدة: 61 → 1900-03-01 · 25569 → 1970-01-01 · 45292 → 2024-01-01.
    if number < 60:
        moment += _DAY
    if moment.hour == moment.minute == moment.second == 0:
        return moment.date()
    return moment


class Sheet:
    def __init__(self, rows: list):
        self._rows = rows                      # list[list[Cell]]

    def __getitem__(self, row_number: int):
        index = row_number - 1
        if index < 0 or index >= len(self._rows):
            return ()
        return tuple(self._rows[index])

    @property
    def max_row(self) -> int:
        return len(self._rows)

    def iter_rows(self, min_row: int = 1, max_row: int | None = None,
                  min_col: int | None = None, max_col: int | None = None,
                  values_only: bool = False):
        last = max_row or len(self._rows)
        last = min(last, len(self._rows))
        for row in self._rows[min_row - 1:last]:
            cells = row[min_col - 1 if min_col else 0: max_col if max_col else None]
            yield tuple(cell.value for cell in cells) if values_only else tuple(cells)


class Workbook:
    def __init__(self, sheets: dict):
        self._sheets = sheets
        self.sheetnames = list(sheets)

    def __getitem__(self, name: str) -> Sheet:
        key = str(name).strip()
        if key not in self._sheets:
            for candidate in self._sheets:
                if candidate.strip() == key:
                    return self._sheets[candidate]
            raise KeyError(f"لا توجد ورقة باسم {name!r}. المتاح: {self.sheetnames}")
        return self._sheets[key]


def _shared_strings(archive: zipfile.ZipFile) -> list:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings = []
    for item in root.findall(f"{MAIN}si"):
        strings.append("".join(node.text or "" for node in item.iter(f"{MAIN}t")))
    return strings


def _date_style_ids(archive: zipfile.ZipFile) -> set:
    """أرقام أنماط الخلايا التي تنسيقها تاريخ — لتحويل السلاسل الرقمية."""
    if "xl/styles.xml" not in archive.namelist():
        return set()
    root = ET.fromstring(archive.read("xl/styles.xml"))
    custom = {}
    for fmt in root.iter(f"{MAIN}numFmt"):
        code = (fmt.get("formatCode") or "").lower()
        # تجاهل تنسيقات الوقت فقط ([h]:mm) وتنسيقات الأرقام
        if re.search(r"[yd]", code) or ("m" in code and "d" in code):
            custom[int(fmt.get("numFmtId") or -1)] = True
    styles = set()
    cell_xfs = root.find(f"{MAIN}cellXfs")
    if cell_xfs is None:
        return styles
    for index, xf in enumerate(cell_xfs.findall(f"{MAIN}xf")):
        fmt_id = int(xf.get("numFmtId") or 0)
        if fmt_id in _DATE_FORMAT_IDS or custom.get(fmt_id):
            styles.add(index)
    return styles


def load_workbook(path: str, data_only: bool = True) -> Workbook:
    """يقرأ ملف xlsx ويعيد كائنًا بواجهة `openpyxl` الجزئية المستخدمة هنا."""
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        date_styles = _date_style_ids(archive)
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = dict(re.findall(
            r'Target="([^"]+)"\s+Id="(rId\d+)"',
            archive.read("xl/_rels/workbook.xml.rels").decode("utf-8"),
        ))
        targets = {rid: target for target, rid in relations.items()}
        sheets: dict = {}
        for element in book.iter(f"{MAIN}sheet"):
            name = element.get("name") or ""
            target = targets.get(element.get(f"{REL}id"), "")
            entry = target.lstrip("/")
            if entry not in archive.namelist():
                sheets[name] = Sheet([])
                continue
            sheets[name] = Sheet(_read_rows(archive.read(entry), shared, date_styles))
    return Workbook(sheets)


def _read_rows(xml_bytes: bytes, shared: list, date_styles: set) -> list:
    root = ET.fromstring(xml_bytes)
    rows = []
    for row in root.iter(f"{MAIN}row"):
        values: dict = {}
        widest = -1
        for cell in row.findall(f"{MAIN}c"):
            index = _column_index(cell.get("r") or "A1")
            widest = max(widest, index)
            kind = cell.get("t")
            if kind == "inlineStr":
                node = cell.find(f"{MAIN}is")
                text = "".join(part.text or "" for part in node.iter(f"{MAIN}t")) if node is not None else ""
                values[index] = text
                continue
            raw = cell.find(f"{MAIN}v")
            text = raw.text if raw is not None else None
            if text is None:
                continue
            if kind == "s":
                values[index] = shared[int(text)] if text.isdigit() and int(text) < len(shared) else ""
            elif kind == "b":
                values[index] = bool(int(text))
            elif kind == "str":
                values[index] = text
            else:
                try:
                    number = float(text)
                except ValueError:
                    values[index] = text
                else:
                    style = int(cell.get("s") or 0)
                    if style in date_styles:
                        values[index] = _serial_to_datetime(number)
                    else:
                        values[index] = int(number) if number.is_integer() else number
        rows.append([Cell(values.get(i)) for i in range(widest + 1)])
    return rows
