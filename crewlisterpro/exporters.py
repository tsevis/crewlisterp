"""Exports only verified trip data; the service is the gatekeeper."""

from __future__ import annotations

import csv
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .domain import Assignment, Boat, Document, Person, Trip


def export_csv(destination: Path, trip: Trip, boat: Boat, people: list[Person], documents: list[Document], assignments: list[Assignment]) -> None:
    by_person = {document.person_id: document for document in documents}
    role_by_person = {assignment.person_id: assignment.role for assignment in assignments}
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "nationality", "birth_date", "document_number", "role"])
        writer.writeheader()
        for person in people:
            document = by_person.get(person.id)
            writer.writerow({
                "name": person.full_name,
                "nationality": person.nationality,
                "birth_date": person.birth_date,
                "document_number": document.document_number if document else "",
                "role": role_by_person.get(person.id, "passenger"),
            })


def export_pdf(destination: Path, trip: Trip, boat: Boat, people: list[Person], documents: list[Document], assignments: list[Assignment]) -> None:
    canvas = Canvas(str(destination), pagesize=A4)
    _width, height = A4
    canvas.setTitle("Crew List")
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(42, height - 48, "CREW LIST")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(42, height - 68, f"Yacht: {boat.name}  |  {boat.flag}  |  {boat.registration_number}")
    canvas.drawString(42, height - 84, f"Trip: {trip.departure_date} to {trip.return_date}")
    y = height - 122
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(42, y, "NAME")
    canvas.drawString(240, y, "NATIONALITY")
    canvas.drawString(350, y, "BIRTH DATE")
    canvas.drawString(440, y, "DOCUMENT")
    canvas.drawString(525, y, "ROLE")
    canvas.setFont("Helvetica", 9)
    by_person = {document.person_id: document for document in documents}
    role_by_person = {assignment.person_id: assignment.role for assignment in assignments}
    for person in people:
        y -= 22
        if y < 48:
            canvas.showPage()
            y = height - 48
        document = by_person.get(person.id)
        canvas.drawString(42, y, person.full_name[:34])
        canvas.drawString(240, y, person.nationality[:16])
        canvas.drawString(350, y, person.birth_date)
        canvas.drawString(440, y, document.document_number if document else "")
        canvas.drawString(525, y, role_by_person.get(person.id, "passenger"))
    canvas.save()
