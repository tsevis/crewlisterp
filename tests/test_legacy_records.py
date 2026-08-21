"""What the app must survive reading out of a store an older or newer build wrote.

The macOS build shipped this bug twice and it is the same bug here, wearing
different clothes.  There, Swift's synthesised ``Codable`` threw on a key it did
not expect; here, ``Document(**raw)`` raises ``TypeError`` the moment a payload
carries a field this build has never heard of — which is exactly what a *newer*
version writing a *new* column does to an older one.  Because every read is a
list comprehension, that one bad record does not fail alone: it takes the whole
collection with it, so a single unreadable row means no trips, no documents and
no crew list at all.

Python adds a failure mode Swift does not have.  Every identity field carries
``default_factory=new_id``, so a payload with no ``id`` does not raise — it
silently mints a *fresh* one.  The record then no longer matches the key it is
stored under, and saving it writes a duplicate rather than an update.  A
silently-renamed passport is worse than one that refuses to load.

The rule these pin, matching the macOS build:

* **Descriptive fields are salvaged**, always in the direction that makes the
  operator look: an unknown ``risk_level`` reads as ``review`` and never
  ``low``, an unknown ``role`` reads as ``passenger`` rather than inventing a
  skipper to name as master of the vessel.
* **Identity is never fabricated.**  A record with no ``id``, ``trip_id`` or
  ``person_id`` is dropped and reported, never silently re-created.

Every payload below is a literal dict in an older or newer shape — input no
code in this repository produced.  A round-trip test that saves and reloads a
record the app just built passes trivially and proves nothing, which is
precisely the test that was in place when the macOS store broke.
"""

from __future__ import annotations

from pathlib import Path

from test_service import MemoryStore, StubOCR

from crewlisterpro.domain import Assignment, Boat, Document, Person, Trip, load_record
from crewlisterpro.service import CrewListrService


def _service(tmp_path: Path) -> CrewListrService:
    return CrewListrService(MemoryStore(tmp_path), ocr=StubOCR())  # type: ignore[arg-type]


# --- Forward compatibility: a column this build has never heard of ----------


def test_a_field_from_a_newer_build_is_ignored_rather_than_fatal() -> None:
    document = load_record(Document, {"id": "a", "trip_id": "t", "person_id": "p", "biometric_hash": "xyz"})
    assert document is not None
    assert document.id == "a"
    assert not hasattr(document, "biometric_hash")


def test_a_boat_from_a_newer_build_survives_its_unknown_columns() -> None:
    boat = load_record(Boat, {"id": "b", "name": "S/Y ANEMOS", "hull_material": "carbon"})
    assert boat is not None
    assert boat.name == "S/Y ANEMOS"


# --- Backward compatibility: columns that did not exist yet -----------------


def test_a_boat_from_before_its_registration_fields_decodes() -> None:
    boat = load_record(Boat, {"id": "b", "name": "S/Y ANEMOS"})
    assert boat is not None
    assert boat.flag == ""
    assert boat.registration_port == ""
    assert boat.registration_number == ""


def test_a_document_from_before_every_optional_field_decodes() -> None:
    document = load_record(Document, {"id": "a", "trip_id": "t", "person_id": "p"})
    assert document is not None
    assert document.fields == {}
    assert document.verified_fields == []
    assert document.risk_level == "review"


# --- Identity is never fabricated -------------------------------------------


def test_a_document_with_no_identity_is_dropped_not_renamed() -> None:
    assert load_record(Document, {"trip_id": "t", "person_id": "p", "file_name": "p.jpeg"}) is None


def test_a_document_belonging_to_no_trip_is_dropped() -> None:
    assert load_record(Document, {"id": "a", "person_id": "p"}) is None


def test_a_document_attached_to_no_person_is_dropped() -> None:
    assert load_record(Document, {"id": "a", "trip_id": "t"}) is None


def test_an_empty_identity_counts_as_no_identity() -> None:
    assert load_record(Document, {"id": "", "trip_id": "t", "person_id": "p"}) is None


def test_a_boat_with_no_identity_is_dropped() -> None:
    assert load_record(Boat, {"name": "S/Y ANEMOS"}) is None


def test_a_trip_with_no_boat_is_dropped() -> None:
    assert load_record(Trip, {"id": "t"}) is None


# --- Descriptive fields fail in the safe direction --------------------------


def test_an_unknown_risk_level_reads_as_needing_review() -> None:
    document = load_record(Document, {"id": "a", "trip_id": "t", "person_id": "p", "risk_level": "catastrophic"})
    assert document is not None
    assert document.risk_level == "review"


def test_an_unknown_risk_level_is_never_downgraded_to_cleared() -> None:
    document = load_record(Document, {"id": "a", "trip_id": "t", "person_id": "p", "risk_level": "???"})
    assert document is not None
    assert document.risk_level != "low"


def test_an_unknown_role_reads_as_passenger() -> None:
    """Guessing skipper would name the wrong person as master of the vessel."""
    assignment = load_record(Assignment, {"id": "x", "trip_id": "t", "person_id": "p", "role": "deckhand"})
    assert assignment is not None
    assert assignment.role == "passenger"


def test_an_unknown_verification_state_reads_as_pending() -> None:
    person = load_record(Person, {"id": "p", "verification_state": "provisional"})
    assert person is not None
    assert person.verification_state == "pending"


def test_a_mistyped_collection_field_falls_back_to_its_default() -> None:
    document = load_record(Document, {"id": "a", "trip_id": "t", "person_id": "p", "verified_fields": "all"})
    assert document is not None
    assert document.verified_fields == []


# --- One bad record must cost one record ------------------------------------


def test_one_unreadable_document_does_not_hide_the_others(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.store.save("trip", "t", {"id": "t", "boat_id": "b", "departure_date": "2026-09-05"})
    service.store.save("document", "good", {"id": "good", "trip_id": "t", "person_id": "p"})
    service.store.save("document", "bad", {"file_name": "orphan.jpeg"})

    documents = service.documents_for_trip("t")

    assert [document.id for document in documents] == ["good"]


def test_a_dropped_record_is_reported(tmp_path: Path) -> None:
    """Salvage that nobody is told about is just quiet data loss."""
    service = _service(tmp_path)
    service.store.save("trip", "t", {"id": "t", "boat_id": "b", "departure_date": "2026-09-05"})
    service.store.save("document", "bad", {"file_name": "orphan.jpeg"})

    service.documents_for_trip("t")

    assert service.decoding_losses
    assert any("document" in loss for loss in service.decoding_losses)


def test_a_wholly_readable_store_reports_no_losses(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.store.save("trip", "t", {"id": "t", "boat_id": "b", "departure_date": "2026-09-05"})
    service.store.save("document", "good", {"id": "good", "trip_id": "t", "person_id": "p"})

    service.documents_for_trip("t")

    assert service.decoding_losses == []


def test_a_document_with_no_trip_key_does_not_crash_the_listing(tmp_path: Path) -> None:
    """``item["trip_id"]`` raised KeyError on a record written before trips."""
    service = _service(tmp_path)
    service.store.save("trip", "t", {"id": "t", "boat_id": "b", "departure_date": "2026-09-05"})
    service.store.save("document", "legacy", {"id": "legacy", "person_id": "p"})

    assert service.documents_for_trip("t") == []


def test_one_unreadable_boat_does_not_hide_the_fleet(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.store.save("boat", "good", {"id": "good", "name": "S/Y ANEMOS"})
    service.store.save("boat", "bad", {"name": "NAMELESS"})

    assert [boat.name for boat in service.boats()] == ["S/Y ANEMOS"]


def test_one_unreadable_trip_does_not_hide_the_season(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.store.save("trip", "good", {"id": "good", "boat_id": "b", "departure_date": "2026-09-05"})
    service.store.save("trip", "bad", {"departure_date": "2026-09-05"})

    assert [trip.id for trip in service.trips()] == ["good"]


# --- No regression on what the app writes today -----------------------------


def test_todays_shape_still_round_trips_unchanged() -> None:
    """Hardening the reader must not change what the writer produces."""
    document = Document(trip_id="t", person_id="p", file_name="p.jpeg", document_number="W1357924D")
    document.fields = {"full_name": "YUKI NAKAMURA"}
    document.verified_fields = ["full_name"]

    restored = load_record(Document, document.payload())

    assert restored == document
