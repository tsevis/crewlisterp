"""The passenger manifest in the port authority's own template.

``docs/passengers_manifest_template.xlsx``: one sheet, nine bilingual columns,
one row per person aboard. Every cell is written as text, as the template's
instructions sheet asks: Excel turns ``2026-07-01`` and ``08:00`` into serial
numbers the importer cannot read, and ``0012345`` into ``12345``.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .domain import Assignment, Document, Person, Trip
from .nationalities import NATIONALITIES

SHEET_NAME = "Passengers"

#: The template's headers, verbatim and in its order. The importer reads by
#: position; nothing here may be reordered.
HEADERS = [
    "Full Name / Ονοματεπώνυμο",
    "ID/Passport No / Αρ. Ταυτότητας/Διαβατηρίου",
    "Sex (M/F) / Φύλο (Α/Θ)",
    "Nationality / Ιθαγένεια",
    "Date of Birth / Ημ. Γέννησης",
    "Embarkation Date / Ημ. Επιβίβασης",
    "Embarkation Time / Ώρα Επιβίβασης",
    "Embarkation Port / Λιμένας Επιβίβασης",
    "Notes / Σημειώσεις",
]
COLUMN_WIDTHS = [28, 22, 10, 12, 14, 16, 14, 20, 24]

#: Spellings the template does not list but documents and the MRZ use. ICAO
#: 9303 writes Germany as ``D``, has five British variants, and ``XXA``-``XXC``
#: for the stateless and refugees that the template folds into ``XXX``.
_ALIASES = {
    "D": "DEU", "DEUTSCH": "DEU", "DEUTSCHE": "DEU",
    "GBD": "GBR", "GBN": "GBR", "GBO": "GBR", "GBP": "GBR", "GBS": "GBR", "BRITISH CITIZEN": "GBR",
    "HELLENIC": "GRC", "ELLINIKI": "GRC",
    "PSE": "TPO", "RKS": "XKX", "KOSOVAR": "XKX",
    "XXA": "XXX", "XXB": "XXX", "XXC": "XXX",
    "ITALIANA": "ITA", "FRANCAISE": "FRA", "ESPANOLA": "ESP", "NEDERLANDSE": "NLD",
    "UNITED STATES OF AMERICA": "USA",
}


def _folded(value: str) -> str:
    """Upper case, no accents, single spaces: ``Ελληνική`` and ``ΕΛΛΗΝΙΚΗ`` are one key."""
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.upper().split())


_LOOKUP = {**{_folded(k): v for k, v in _ALIASES.items()},
           **{_folded(name): code for code, english, greek in NATIONALITIES for name in (code, english, greek)}}


def nationality_code(value: str) -> str | None:
    """The template's code for ``value``, or ``None`` rather than a guess.

    A wrong code on a government upload declares the wrong citizenship; an
    unresolved one is a cell the importer rejects and the operator fixes.
    """
    key = _folded(value)
    return _LOOKUP.get(key) if key else None


_TIME = re.compile(r"^(\d{1,2})[:.](\d{2})$|^(\d{2})(\d{2})$")


def embarkation_time(value: str) -> str | None:
    """``8:00``, ``0800`` and ``08.00`` become ``08:00``; empty stays empty; ``None`` is not a time."""
    trimmed = value.strip()
    if not trimmed:
        return ""
    match = _TIME.match(trimmed)
    if match is None:
        return None
    hour, minute = (int(part) for part in (match.group(1) or match.group(3), match.group(2) or match.group(4)))
    return f"{hour:02d}:{minute:02d}" if hour <= 23 and minute <= 59 else None


def manifest_lines(trip: Trip, people: list[Person], documents: list[Document],
                   assignments: list[Assignment]) -> list[list[str]]:
    """Header row, then one line per person — the skipper included and said so in Notes."""
    by_person = {document.person_id: document for document in documents}
    role_by_person = {assignment.person_id: assignment.role for assignment in assignments}
    lines = [list(HEADERS)]
    for person in people:
        document = by_person.get(person.id)
        fields = document.fields if document else {}
        lines.append([
            person.full_name,
            document.document_number if document else "",
            (fields.get("sex") or person.sex).upper(),
            # Written as read when unresolved, rather than blank: an empty cell
            # hides which person needs fixing.
            nationality_code(person.nationality) or person.nationality,
            person.birth_date,
            trip.departure_date,
            trip.embarkation_time,
            trip.embarkation_port,
            "Skipper" if role_by_person.get(person.id) == "skipper" else "",
        ])
    return lines


def write_manifest(destination: Path, trip: Trip, people: list[Person], documents: list[Document],
                   assignments: list[Assignment]) -> None:
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "xl/workbook.xml": _workbook(),
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/styles.xml": _STYLES,
        "xl/worksheets/sheet1.xml": _sheet(manifest_lines(trip, people, documents, assignments)),
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml)


# --- SpreadsheetML ------------------------------------------------------------

_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _text(value: str) -> str:
    """XML-escaped, minus the control characters XML 1.0 forbids: one stray OCR byte
    would otherwise make Excel refuse the whole file."""
    return escape(_CONTROL.sub("", value), {'"': "&quot;", "'": "&apos;"})


def _column(index: int) -> str:
    name, remaining = "", index + 1
    while remaining:
        remaining, digit = divmod(remaining - 1, 26)
        name = chr(65 + digit) + name
    return name


def _sheet(lines: list[list[str]]) -> str:
    """Style 1 is text, style 2 bold text; every column is styled text too, so a row
    the operator adds in Excel afterwards stays text as well."""
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" style="1" customWidth="1"/>'
                   for i, w in enumerate(COLUMN_WIDTHS))
    rows = "".join(
        f'<row r="{r + 1}">' + "".join(
            f'<c r="{_column(c)}{r + 1}" s="{2 if r == 0 else 1}" t="inlineStr">'
            f'<is><t xml:space="preserve">{_text(value)}</t></is></c>'
            for c, value in enumerate(line)) + "</row>"
        for r, line in enumerate(lines))
    return (f'{_XML}<worksheet xmlns="{_MAIN}"><sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f"<cols>{cols}</cols><sheetData>{rows}</sheetData></worksheet>")


def _workbook() -> str:
    return (f'{_XML}<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets>'
            f'<sheet name="{_text(SHEET_NAME)}" sheetId="1" r:id="rId1"/></sheets></workbook>')


_CONTENT_TYPES = (
    f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "</Types>"
)
_ROOT_RELS = (f'{_XML}<Relationships xmlns="{_PKG}">'
              f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
_WORKBOOK_RELS = (f'{_XML}<Relationships xmlns="{_PKG}">'
                  f'<Relationship Id="rId1" Type="{_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
                  f'<Relationship Id="rId2" Type="{_REL}/styles" Target="styles.xml"/></Relationships>')
#: numFmtId 49 is Excel's built-in Text format, ``@``.
_STYLES = (
    f'{_XML}<styleSheet xmlns="{_MAIN}">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="49" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
    "</cellXfs><cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
    "</styleSheet>"
)
