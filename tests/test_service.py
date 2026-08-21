import csv
from datetime import date
from pathlib import Path

from PIL import Image

from crewlisterpro.ocr import Extraction
from crewlisterpro.service import CrewListrService


class MemoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: dict[tuple[str, str], dict[str, object]] = {}

    def save(self, kind: str, record_id: str, payload: dict[str, object]) -> None:
        self.records[(kind, record_id)] = payload

    def get(self, kind: str, record_id: str) -> dict[str, object] | None:
        return self.records.get((kind, record_id))

    def list(self, kind: str) -> list[dict[str, object]]:
        return [payload for (record_kind, _), payload in self.records.items() if record_kind == kind]

    def write_document(self, document_id: str, source: Path) -> tuple[str, str]:
        target = self.root / f"{document_id}.bin"
        target.write_bytes(source.read_bytes())
        return str(target), "hash"

    def read_document(self, encrypted_path: str) -> bytes:
        return Path(encrypted_path).read_bytes()

    def delete_document(self, encrypted_path: str) -> None:
        Path(encrypted_path).unlink(missing_ok=True)

    def delete(self, kind: str, record_id: str) -> None:
        self.records.pop((kind, record_id), None)


class StubOCR:
    def extract(self, _image: Image.Image) -> Extraction:
        return Extraction(
            {"full_name": "ANNA TEST", "document_number": "AB123456", "nationality": "GREEK"},
            "review",
            ["Manual review required."],
            False,
            "",
        )


def test_review_gate_and_verified_exports(tmp_path: Path) -> None:
    service = CrewListrService(MemoryStore(tmp_path), ocr=StubOCR())  # type: ignore[arg-type]
    boat = service.create_boat("Mio", "Greek", "Piraeus", "123")
    trip = service.create_trip(boat.id, date(2026, 8, 1), date(2026, 8, 8))
    source = tmp_path / "passport.png"
    Image.new("RGB", (10, 10), "white").save(source)
    document = service.import_document(trip.id, source)
    allowed, _ = service.exportable(trip.id)
    assert not allowed
    service.verify_document(document.id, document.fields)
    service.assign_role(trip.id, document.person_id, "skipper")
    csv_path, pdf_path = service.export_trip(trip.id, tmp_path / "exports")
    assert csv_path.exists()
    assert pdf_path.exists()
    assert next(csv.DictReader(csv_path.open(encoding="utf-8")))["role"] == "skipper"
