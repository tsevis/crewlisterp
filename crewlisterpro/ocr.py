"""Bounded local OCR and MRZ extraction, designed to fail safely to review."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import cast

from PIL import Image, ImageEnhance, ImageOps

MRZ_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<"


@dataclass(frozen=True, slots=True)
class Extraction:
    fields: dict[str, str]
    risk_level: str
    reasons: list[str]
    mrz_valid: bool
    text: str


def load_image(raw: bytes, name: str) -> Image.Image:
    try:
        image = Image.open(BytesIO(raw))
        image.load()
        return image.convert("RGB")
    except (OSError, ValueError):
        return _render_pdf(raw, name)


def _render_pdf(raw: bytes, name: str) -> Image.Image:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - installer guarantees this.
        raise ValueError(f"Cannot render {name}: PDF renderer unavailable.") from exc
    document = pdfium.PdfDocument(raw)
    bitmap = document[0].render(scale=2.2)
    return cast(Image.Image, bitmap.to_pil().convert("RGB"))


def checksum(value: str) -> int:
    weights = (7, 3, 1)
    total = 0
    for index, character in enumerate(value):
        digit = int(character) if character.isdigit() else ord(character) - ord("A") + 10 if character.isalpha() else 0
        total += digit * weights[index % len(weights)]
    return total % 10


def parse_mrz(text: str) -> dict[str, str] | None:
    """Read an ICAO 9303 TD3 zone.

    Line 2 carries a check digit for the document number, the birth date and
    the expiry date; line 1 carries none. Line 2 is therefore trusted on its
    own arithmetic and line 1 is treated as best effort — a photographed
    passport very often yields a perfect line 2 beside a line 1 the camera
    smeared, and discarding both loses everything the document could still say.
    """
    lines = [re.sub(r"[^A-Z0-9<]", "", line.upper()) for line in text.splitlines()]
    lines = [line for line in lines if len(line) >= 28]
    for index, line in enumerate(lines):
        fields = _parse_mrz_line2(line)
        if fields is None:
            continue
        neighbours = (
            lines[index - 1] if index > 0 else None,
            lines[index + 1] if index + 1 < len(lines) else None,
        )
        fields["full_name"] = next(
            (name for name in (_parse_mrz_names(n) for n in neighbours if n) if name),
            "",
        )
        fields["document_type"] = "passport"
        return fields
    return None


def _parse_mrz_line2(line: str) -> dict[str, str] | None:
    """Every field on line 2 that carries a check digit, or nothing."""
    if len(line) < 28 or not line[9].isdigit():
        return None
    number = _normalize_passport_number(line[:9])
    checksum_source = f"{number:<9}".replace(" ", "<")[:9]
    if not number or checksum(checksum_source) != int(line[9]):
        return None

    birth_raw, expiry_raw = line[13:19], line[21:27]
    if not line[19].isdigit() or checksum(birth_raw) != int(line[19]):
        return None
    if not line[27].isdigit() or checksum(expiry_raw) != int(line[27]):
        return None
    birth = _mrz_date(birth_raw, "birth")
    expiry = _mrz_date(expiry_raw, "expiry")
    if not birth or not expiry:
        return None

    return {
        "document_number": number,
        "nationality": nationality(line[10:13]),
        "birth_date": birth,
        "expiry_date": expiry,
        "sex": line[20] if line[20] in {"M", "F"} else "",
    }


def _repair_name_separator(names_zone: str) -> str:
    """Restore a "<<" separator that OCR read as "K<".

    Only a "K<" that is not itself part of "K<<" can be the separator, and only
    one occurring before any real "<<". Repairing eagerly ate the K off every
    surname that legitimately ends in one — MINCHUK became MINCHU — while never
    repairing lost names like STETSENKOK<DIANA, where "K<" really is the break.
    """
    real = names_zone.find("<<")
    for index in range(len(names_zone) - 1):
        if names_zone[index : index + 2] != "K<":
            continue
        if names_zone[index + 2 : index + 3] == "<":
            continue   # "K<<": a genuine K before a real separator
        if real == -1 or index < real:
            return names_zone[:index] + "<<" + names_zone[index + 2 :]
        break
    return names_zone


def _parse_mrz_names(line: str) -> str:
    """``P<UTOERIKSSON<<ANNA<MARIA<<<`` -> ``ANNA MARIA ERIKSSON``.

    Line 1 holds letters and fillers only. A digit means OCR turned security
    print into text, and every character on the line is then suspect: better no
    name than an invented one on a crew list.
    """
    # A TD3 name zone is letters and fillers. "0" is a routine misread of "O"
    # and is repaired below, but any other digit means OCR turned security print
    # into text and the whole line is suspect.
    if len(line) < 10 or any(character.isdigit() and character != "0" for character in line):
        return ""
    names_zone = _repair_name_separator(line[5:])
    if "<<" not in names_zone:
        return ""
    surname_raw, given_raw = names_zone.split("<<", 1)
    surname = normalize_name(surname_raw.replace("0", "O").replace("<", " "))
    # The name field ends at its first run of two fillers; the rest is padding.
    # Single-character tokens in that field are filler debris rather than given
    # names — "DIANA<K" is DIANA beside a stray K, not a middle initial.
    given_tokens = [
        token for token in given_raw.split("<<")[0].replace("0", "O").split("<") if len(token) > 1
    ]
    given = normalize_name(" ".join(given_tokens))
    if not surname or not given:
        return ""
    return f"{given} {surname}"


def _normalize_passport_number(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{6,7}", normalized):
        suffix = normalized[2:]
        for letter, digit in (("O", "0"), ("I", "1"), ("Z", "2"), ("S", "5"), ("B", "8")):
            suffix = suffix.replace(letter, digit)
        normalized = normalized[:2] + suffix
    return normalized


def _mrz_date(value: str, kind: str = "birth", today: date | None = None) -> str:
    """Resolve a two-digit MRZ year.

    The direction of the ambiguity depends on what the date means: a birth date
    is always in the past, an expiry date on a presented document is essentially
    always ahead. A fixed pivot got both wrong — it read a 2035 expiry as 1935.
    """
    if len(value) != 6 or not value.isdigit():
        return ""
    today = today or datetime.now(tz=UTC).date()
    candidate = today.year - today.year % 100 + int(value[:2])
    if kind == "birth":
        year = candidate - 100 if candidate > today.year else candidate
    else:
        # A passport issued today can run ten years out, so let the window
        # cross the century rather than dragging a future expiry backwards.
        year = candidate + 100 if candidate < today.year - 10 else candidate
    try:
        return date(year, int(value[2:4]), int(value[4:6])).isoformat()
    except ValueError:
        return ""


def nationality(code: str) -> str:
    return {"UKR": "UKRAINIAN", "GRC": "GREEK", "ITA": "ITALIAN", "RUS": "RUSSIAN", "POL": "POLISH"}.get(code, code)


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z' -]", " ", value.upper())).strip()


class LocalOCR:
    """At most six Tesseract operations, each limited to 12 seconds."""

    def __init__(self, tesseract: str | None = None, timeout_seconds: int = 12):
        self.tesseract = tesseract or shutil.which("tesseract")
        self.timeout_seconds = timeout_seconds

    def extract(self, image: Image.Image) -> Extraction:
        if not self.tesseract:
            return Extraction({}, "review", ["Tesseract is not installed."], False, "")
        best_text = ""
        # Do not nest every rotation with every transform. This explicit three-
        # candidate budget handles common phone photos without an unbounded sweep.
        sequence = ((0, 0), (0, 1), (0, 2)) if image.width >= image.height else ((0, 0), (90, 0), (90, 1))
        for rotation, variant_index in sequence:
            rotated = image.rotate(rotation, expand=True)
            candidate = self._variants(rotated)[variant_index]
            mrz_text = self._run(candidate, ["-c", f"tessedit_char_whitelist={MRZ_CHARS}"], "eng")
            parsed = parse_mrz(mrz_text)
            text = self._run(candidate, [], "eng+ukr+rus+ell")
            best_text = text if len(text) > len(best_text) else best_text
            if parsed:
                return Extraction(parsed, "low", ["Checksum-valid MRZ."], True, text or mrz_text)
        fields = fallback_fields(best_text)
        reasons = ["No checksum-valid MRZ; review all suggested fields."]
        if not fields.get("document_number"):
            reasons.append("Document number is missing.")
        return Extraction(fields, "review", reasons, False, best_text)

    def _variants(self, image: Image.Image) -> tuple[Image.Image, Image.Image, Image.Image]:
        gray = ImageOps.grayscale(image)
        contrast = ImageEnhance.Contrast(gray).enhance(1.5).convert("RGB")
        stronger_contrast = ImageEnhance.Contrast(gray).enhance(1.9).convert("RGB")
        return image, contrast, stronger_contrast

    def _run(self, image: Image.Image, extra: list[str], languages: str) -> str:
        # A temporary *directory*, not NamedTemporaryFile: the latter keeps an
        # exclusive handle open for its lifetime, so on Windows neither PIL nor
        # tesseract can open the path while it exists. Both need to open it by
        # name, so nothing may be holding it.
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "page.png"
            image.save(page)
            try:
                result = subprocess.run(
                    [self.tesseract or "tesseract", str(page), "stdout", "--psm", "6", "-l", languages, *extra],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return ""
        return result.stdout.strip()


def fallback_fields(text: str) -> dict[str, str]:
    upper = text.upper()
    fields: dict[str, str] = {}
    number = re.search(r"\b[A-Z]{2}\s?\d{6,7}\b", upper)
    if number:
        fields["document_number"] = number.group().replace(" ", "")
    date_match = re.search(r"\b(\d{2})[./-](\d{2})[./-](\d{4})\b", upper)
    if date_match:
        fields["birth_date"] = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
    for value, label in (("UKRAINE", "UKRAINIAN"), ("GREECE", "GREEK"), ("ITALY", "ITALIAN")):
        if value in upper:
            fields["nationality"] = label
            break
    return fields
