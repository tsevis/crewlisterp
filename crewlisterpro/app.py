"""PySide6 entry point for the compact cross-platform CrewListr Pro workflow."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from .models import OLLAMA_MODEL, OLLAMA_SIZE_BYTES, OllamaManager
from .service import CrewListrService
from .storage import EncryptedStore, StorageUnavailable


def app_data_dir() -> Path:
    return Path.home() / ".crewlisterpro"


def main() -> None:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QApplication,
            QFileDialog,
            QInputDialog,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QToolBar,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        raise SystemExit("CrewListr Pro was installed without PySide6.") from exc

    application = QApplication(sys.argv)
    passphrase, accepted = QInputDialog.getText(None, "Unlock CrewListr Pro", "Master passphrase:", QLineEdit.EchoMode.Password)
    if not accepted:
        return
    try:
        service = CrewListrService(EncryptedStore(app_data_dir(), passphrase))
    except (StorageUnavailable, ValueError) as exc:
        QMessageBox.critical(None, "Cannot open encrypted data", str(exc))
        return

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.service = service
            self.models = OllamaManager()
            self.trip_id: str | None = None
            self.setWindowTitle("CrewListr Pro")
            self.resize(1100, 700)
            self.status = QLabel("Create a trip, import documents, then verify every suggested field.")
            self.table = QTableWidget(0, 6)
            self.table.setHorizontalHeaderLabels(["Document", "Name", "Document no.", "Role", "Risk", "Verification"])
            self.table.horizontalHeader().setStretchLastSection(True)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.addWidget(self.status)
            layout.addWidget(self.table)
            self.setCentralWidget(content)
            toolbar = QToolBar("Workflow")
            self.addToolBar(toolbar)
            for title, callback in (("New trip", self.new_trip), ("Import document", self.import_document), ("Verify selected", self.verify_selected), ("Export verified", self.export_trip), ("Local AI", self.prepare_local_ai)):
                action = toolbar.addAction(title)
                action.triggered.connect(callback)
            self.import_button = QPushButton("Import document")
            self.import_button.clicked.connect(self.import_document)
            layout.addWidget(self.import_button, alignment=Qt.AlignmentFlag.AlignLeft)

        def new_trip(self) -> None:
            yacht, ok = QInputDialog.getText(self, "New trip", "Yacht name:")
            if not ok or not yacht.strip():
                return
            boat = self.service.create_boat(yacht, "", "", "")
            today = datetime.now(UTC).date()
            trip = self.service.create_trip(boat.id, today, today)
            self.trip_id = trip.id
            self.status.setText("Trip ready. Import images or PDFs; exports remain disabled until review.")
            self.refresh()

        def import_document(self) -> None:
            if not self.trip_id:
                QMessageBox.information(self, "Create a trip first", "A document always belongs to a trip.")
                return
            file_name, _ = QFileDialog.getOpenFileName(self, "Import identity document", "", "Documents (*.png *.jpg *.jpeg *.pdf)")
            if not file_name:
                return
            try:
                self.service.import_document(self.trip_id, Path(file_name))
            except (OSError, RuntimeError, ValueError) as exc:
                QMessageBox.warning(self, "Import failed", str(exc))
                return
            self.refresh()

        def verify_selected(self) -> None:
            row = self.table.currentRow()
            if row < 0 or not self.trip_id:
                return
            item = self.table.item(row, 0)
            if item is None:
                return
            document_id = item.data(Qt.ItemDataRole.UserRole)
            document = next(item for item in self.service.documents_for_trip(self.trip_id) if item.id == document_id)
            reviewed = dict(document.fields)
            for field, label in (("full_name", "Full name"), ("document_number", "Document number"), ("nationality", "Nationality"), ("birth_date", "Birth date (YYYY-MM-DD)"), ("sex", "Sex")):
                value, accepted = QInputDialog.getText(self, "Verify document", label, text=reviewed.get(field, ""))
                if not accepted:
                    return
                reviewed[field] = value
            selected_role, accepted = QInputDialog.getItem(self, "Crew role", "Role:", ["passenger", "skipper"], 0, False)
            if not accepted:
                return
            self.service.verify_document(document.id, reviewed)
            self.service.assign_role(self.trip_id, document.person_id, selected_role)
            self.refresh()

        def export_trip(self) -> None:
            if not self.trip_id:
                return
            destination = QFileDialog.getExistingDirectory(self, "Choose export folder")
            if not destination:
                return
            try:
                csv_path, pdf_path = self.service.export_trip(self.trip_id, Path(destination))
            except ValueError as exc:
                QMessageBox.warning(self, "Export blocked", str(exc))
                return
            self.status.setText(f"Exported {csv_path.name} and {pdf_path.name}.")

        def prepare_local_ai(self) -> None:
            status = self.models.status()
            if not status.runtime_available:
                QMessageBox.information(self, "Install Ollama", "Install Ollama for your platform, then select Local AI again. OCR/MRZ works without it.")
                return
            if status.model_present:
                self.service.model_manager = self.models
                self.status.setText(f"{OLLAMA_MODEL} is ready for low-confidence document rescue.")
                return
            readiness = self.models.download_readiness()
            if not readiness.ready:
                QMessageBox.warning(self, "Local AI unavailable", readiness.message)
                self.status.setText("Continuing in OCR/MRZ-only mode.")
                return
            answer = QMessageBox.question(self, "Download local AI", f"Download {OLLAMA_MODEL} ({OLLAMA_SIZE_BYTES / 1_000_000_000:.1f} GB)? It stays on this computer and is optional.")
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setText("Continuing in OCR/MRZ-only mode.")
                return
            self.status.setText("Downloading local AI…")
            try:
                self.models.pull()
            except RuntimeError as exc:
                QMessageBox.warning(self, "Download failed", str(exc))
                self.status.setText("Continuing in OCR/MRZ-only mode.")
                return
            self.status.setText(f"{OLLAMA_MODEL} is ready for low-confidence document rescue.")
            self.service.model_manager = self.models

        def refresh(self) -> None:
            documents = self.service.documents_for_trip(self.trip_id) if self.trip_id else []
            self.table.setRowCount(len(documents))
            for row, document in enumerate(documents):
                role = self.service.role_for_person(self.trip_id, document.person_id) if self.trip_id else "passenger"
                values = [document.file_name, document.fields.get("full_name", ""), document.document_number, role, document.risk_level, "verified" if document.verified_fields else "pending"]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, document.id)
                    self.table.setItem(row, column, item)

    window = Window()
    window.show()
    exit_code = application.exec()
    service.store.close()
    raise SystemExit(exit_code)
