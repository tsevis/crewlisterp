"""Application workflow: extracted values stay pending until explicitly verified."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import TypeVar

from .domain import Assignment, Boat, Document, Person, Trip, load_record
from .exporters import export_csv, export_pdf
from .models import OllamaManager
from .ocr import LocalOCR, load_image
from .storage import EncryptedStore

_Record = TypeVar("_Record")


class CrewListrService:
    def __init__(self, store: EncryptedStore, ocr: LocalOCR | None = None, model_manager: OllamaManager | None = None):
        self.store = store
        self.ocr = ocr or LocalOCR()
        self.model_manager = model_manager
        self._losses: dict[str, int] = {}

    @property
    def decoding_losses(self) -> list[str]:
        """Records the last read could not trust, described for the operator.

        Salvage that nobody is told about is just quiet data loss: a dropped
        document is a passport missing from a trip, and an operator who is not
        told finds out when a port authority counts heads.
        """
        return [
            f"{count} {noun}{'' if count == 1 else 's'} could not be read and "
            f"{'was' if count == 1 else 'were'} left out."
            for noun, count in sorted(self._losses.items())
            if count
        ]

    def _load_all(self, kind: str, cls: type[_Record], noun: str) -> list[_Record]:
        """Reads a whole collection, dropping only the records it cannot trust.

        Previously a list comprehension over ``cls(**payload)``: one record
        carrying a field this build did not know raised ``TypeError`` and took
        the entire collection with it, so a single bad row meant no trips and no
        crew list at all.
        """
        recovered: list[_Record] = []
        lost = 0
        for payload in self.store.list(kind):
            record = load_record(cls, payload)
            if record is None:
                lost += 1
            else:
                recovered.append(record)
        self._losses[noun] = lost
        return recovered

    def _load_one(self, kind: str, record_id: str, cls: type[_Record]) -> _Record | None:
        payload = self.store.get(kind, record_id)
        return load_record(cls, payload) if payload is not None else None

    def create_boat(self, name: str, flag: str, port: str, number: str) -> Boat:
        boat = Boat(name=name.strip().upper(), flag=flag.strip().upper(), registration_port=port.strip().upper(), registration_number=number.strip().upper())
        if not boat.name:
            raise ValueError("Boat name is required.")
        self.store.save("boat", boat.id, boat.payload())
        return boat

    def create_trip(self, boat_id: str, departure: date, return_date: date) -> Trip:
        if return_date < departure:
            raise ValueError("Return date must not precede departure date.")
        trip = Trip(boat_id=boat_id, departure_date=departure.isoformat(), return_date=return_date.isoformat())
        self.store.save("trip", trip.id, trip.payload())
        return trip

    def import_document(self, trip_id: str, source: Path, role: str = "passenger") -> Document:
        if not self.store.get("trip", trip_id):
            raise ValueError("Trip not found.")
        document = Document(trip_id=trip_id, file_name=source.name)
        document.content_path, document.sha256 = self.store.write_document(document.id, source)
        raw_bytes = self.store.read_document(document.content_path)
        extraction = self.ocr.extract(load_image(raw_bytes, source.name))
        fields = dict(extraction.fields)
        source_name = "ocr"
        if extraction.risk_level != "low" and self.model_manager and self.model_manager.status().model_present:
            suggested = self.model_manager.extract_document_fields(raw_bytes)
            if suggested:
                fields.update({key: value for key, value in suggested.items() if not fields.get(key)})
                source_name = "ollama_vl"
        document.fields = fields
        document.document_number = fields.get("document_number", "")
        document.document_type = fields.get("document_type", "unknown")
        document.risk_level = extraction.risk_level  # type: ignore[assignment]
        document.risk_reasons = extraction.reasons
        document.source = source_name
        person = Person(
            full_name=fields.get("full_name", ""),
            nationality=fields.get("nationality", ""),
            birth_date=fields.get("birth_date", ""),
            sex=fields.get("sex", ""),
        )
        document.person_id = person.id
        self.store.save("person", person.id, person.payload())
        assignment = Assignment(trip_id=trip_id, person_id=person.id, role=role)  # type: ignore[arg-type]
        self.store.save("assignment", assignment.id, asdict(assignment))
        self.store.save("document", document.id, document.payload())
        return document

    def verify_document(self, document_id: str, fields: dict[str, str]) -> Document:
        document = self._load_one("document", document_id, Document)
        if document is None:
            raise ValueError("Document not found, or its stored record could not be read.")
        document.fields.update({key: value.strip().upper() for key, value in fields.items() if value.strip()})
        document.document_number = document.fields.get("document_number", document.document_number)
        document.verified_fields = sorted(document.fields)
        document.risk_level = "low"
        document.risk_reasons = ["Verified by operator."]
        self.store.save("document", document.id, document.payload())
        person = self._load_one("person", document.person_id, Person)
        if person is not None:
            person.full_name = document.fields.get("full_name", person.full_name)
            person.nationality = document.fields.get("nationality", person.nationality)
            person.birth_date = document.fields.get("birth_date", person.birth_date)
            person.verification_state = "verified"
            self.store.save("person", person.id, person.payload())
        return document

    def documents_for_trip(self, trip_id: str) -> list[Document]:
        # Filtered after loading, not before: reading `payload["trip_id"]`
        # raised KeyError on any record written before that column existed.
        return [document for document in self._load_all("document", Document, "document")
                if document.trip_id == trip_id]

    def boats(self) -> list[Boat]:
        return self._load_all("boat", Boat, "boat")

    def trips(self, include_archived: bool = False) -> list[Trip]:
        records = self._load_all("trip", Trip, "trip")
        return records if include_archived else [trip for trip in records if trip.status != "archived"]

    def exportable(self, trip_id: str) -> tuple[bool, list[str]]:
        documents = self.documents_for_trip(trip_id)
        problems = [document.file_name for document in documents if document.risk_level != "low" or not document.verified_fields]
        return not problems and bool(documents), problems

    def export_trip(self, trip_id: str, destination: Path) -> tuple[Path, Path]:
        allowed, problems = self.exportable(trip_id)
        if not allowed:
            raise ValueError(f"Export is blocked until review is complete: {', '.join(problems) or 'no documents'}.")
        trip = self._load_one("trip", trip_id, Trip)
        if trip is None:
            raise ValueError("Trip not found, or its stored record could not be read.")
        boat = self._load_one("boat", trip.boat_id, Boat)
        if boat is None:
            raise ValueError("Boat not found, or its stored record could not be read.")
        documents = self.documents_for_trip(trip_id)
        wanted = {document.person_id for document in documents}
        people = [person for person in self._load_all("person", Person, "person") if person.id in wanted]
        assignments = [assignment for assignment in self._load_all("assignment", Assignment, "crew assignment")
                       if assignment.trip_id == trip_id]
        destination.mkdir(parents=True, exist_ok=True)
        stem = f"crew-list-{trip.departure_date}"
        csv_path, pdf_path = destination / f"{stem}.csv", destination / f"{stem}.pdf"
        export_csv(csv_path, trip, boat, people, documents, assignments)
        export_pdf(pdf_path, trip, boat, people, documents, assignments)
        return csv_path, pdf_path

    def assign_role(self, trip_id: str, person_id: str, role: str) -> Assignment:
        if role not in {"skipper", "passenger"}:
            raise ValueError("Crew role must be skipper or passenger.")
        for assignment in self._load_all("assignment", Assignment, "crew assignment"):
            if assignment.trip_id == trip_id and assignment.person_id == person_id:
                assignment.role = role  # type: ignore[assignment]
                self.store.save("assignment", assignment.id, assignment.payload())
                return assignment
        assignment = Assignment(trip_id=trip_id, person_id=person_id, role=role)  # type: ignore[arg-type]
        self.store.save("assignment", assignment.id, assignment.payload())
        return assignment

    def role_for_person(self, trip_id: str, person_id: str) -> str:
        for assignment in self._load_all("assignment", Assignment, "crew assignment"):
            if assignment.trip_id == trip_id and assignment.person_id == person_id:
                return str(assignment.role)
        return "passenger"

    def archive_trip(self, trip_id: str) -> None:
        trip = self._load_one("trip", trip_id, Trip)
        if trip is None:
            raise ValueError("Trip not found, or its stored record could not be read.")
        trip.status = "archived"
        self.store.save("trip", trip.id, trip.payload())

    def delete_trip(self, trip_id: str) -> None:
        for document in self.documents_for_trip(trip_id):
            if document.content_path:
                self.store.delete_document(document.content_path)
            self.store.delete("document", document.id)
        for assignment in self.store.list("assignment"):
            if assignment["trip_id"] == trip_id:
                self.store.delete("assignment", str(assignment["id"]))
        self.store.delete("trip", trip_id)
