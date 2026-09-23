import zipfile
from datetime import date
from pathlib import Path

import pytest
from PIL import Image
from test_service import MemoryStore, StubOCR

from crewlisterpro.domain import Assignment, Document, Person, Trip, load_record
from crewlisterpro.manifest import HEADERS, embarkation_time, manifest_lines, nationality_code, write_manifest
from crewlisterpro.service import CrewListrService


def _trip() -> Trip:
    return Trip(boat_id="b", departure_date="2026-07-01", return_date="2026-07-08",
                embarkation_time="08:00", embarkation_port="LAVRIO")


def _crew(role: str = "passenger", nationality: str = "ITALIAN") -> tuple[list[Person], list[Document], list[Assignment]]:
    person = Person(full_name="MARIA ROSSI", nationality=nationality, birth_date="1990-03-22", sex="F")
    document = Document(person_id=person.id, document_number="0012345", fields={"sex": "F"})
    assignment = Assignment(person_id=person.id, role=role)  # type: ignore[arg-type]
    return [person], [document], [assignment]


@pytest.mark.parametrize(("value", "code"), [
    ("GREEK", "GRC"), ("grc", "GRC"), (" Ελληνική ", "GRC"), ("HELLENIC", "GRC"),
    ("Congolese (DRC)", "COD"), ("D", "DEU"), ("PSE", "TPO"), ("RKS", "XKX"), ("GBD", "GBR"),
])
def test_nationality_resolves_to_the_templates_code(value: str, code: str) -> None:
    assert nationality_code(value) == code


def test_an_unknown_nationality_is_not_guessed() -> None:
    assert nationality_code("UTO") is None
    assert nationality_code("") is None


@pytest.mark.parametrize(("value", "normalised"), [
    ("8:00", "08:00"), ("0830", "08:30"), ("14.15", "14:15"), ("", ""),
    ("25:00", None), ("12:60", None), ("noon", None),
])
def test_embarkation_time_is_two_digit_hours_and_minutes(value: str, normalised: str | None) -> None:
    assert embarkation_time(value) == normalised


def test_rows_follow_the_templates_column_order() -> None:
    lines = manifest_lines(_trip(), *_crew())
    assert lines[0] == HEADERS
    assert lines[1] == ["MARIA ROSSI", "0012345", "F", "ITA", "1990-03-22", "2026-07-01", "08:00", "LAVRIO", ""]


def test_the_skipper_is_marked_in_notes() -> None:
    assert manifest_lines(_trip(), *_crew(role="skipper"))[1][-1] == "Skipper"


def test_an_unresolved_nationality_is_written_as_read() -> None:
    assert manifest_lines(_trip(), *_crew(nationality="UTO"))[1][3] == "UTO"


def test_workbook_is_a_valid_archive_with_every_cell_as_text(tmp_path: Path) -> None:
    people, documents, assignments = _crew()
    people[0].full_name = "O'BRIEN & <SONS>"
    target = tmp_path / "manifest.xlsx"
    write_manifest(target, _trip(), people, documents, assignments)

    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert 'name="Passengers"' in archive.read("xl/workbook.xml").decode()
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "O&apos;BRIEN &amp; &lt;SONS&gt;" in sheet
    assert '<t xml:space="preserve">0012345</t>' in sheet
    assert "<v>" not in sheet, "a numeric cell is one Excel turns into a number or a serial date"


def test_a_trip_saved_before_embarkation_existed_still_loads() -> None:
    trip = load_record(Trip, {"id": "t", "boat_id": "b", "departure_date": "2026-07-01"})
    assert trip is not None
    assert (trip.embarkation_time, trip.embarkation_port) == ("", "")


def test_export_writes_the_manifest_beside_the_crew_list(tmp_path: Path) -> None:
    service = CrewListrService(MemoryStore(tmp_path), ocr=StubOCR())  # type: ignore[arg-type]
    boat = service.create_boat("Mio", "GRC", "Piraeus", "123")
    trip = service.create_trip(boat.id, date(2026, 8, 1), date(2026, 8, 8))
    service.set_embarkation(trip.id, "9:30", "piraeus")
    source = tmp_path / "passport.png"
    Image.new("RGB", (10, 10), "white").save(source)
    document = service.import_document(trip.id, source)
    service.verify_document(document.id, document.fields)

    written = service.export_trip(trip.id, tmp_path / "exports")

    assert [path.suffix for path in written] == [".csv", ".pdf", ".xlsx"]
    sheet = zipfile.ZipFile(written[2]).read("xl/worksheets/sheet1.xml").decode()
    assert ">09:30<" in sheet and ">PIRAEUS<" in sheet and ">GRC<" in sheet


def test_an_invalid_embarkation_time_is_refused(tmp_path: Path) -> None:
    service = CrewListrService(MemoryStore(tmp_path), ocr=StubOCR())  # type: ignore[arg-type]
    trip = service.create_trip(service.create_boat("Mio", "", "", "").id, date(2026, 8, 1), date(2026, 8, 8))
    with pytest.raises(ValueError):
        service.set_embarkation(trip.id, "noon", "PIRAEUS")
