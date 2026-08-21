"""Optional local VLM management through an installed Ollama runtime."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

OLLAMA_MODEL = "qwen2.5vl:3b"
OLLAMA_SIZE_BYTES = 3_200_000_000


@dataclass(frozen=True, slots=True)
class ModelStatus:
    runtime_available: bool
    model_present: bool
    message: str


@dataclass(frozen=True, slots=True)
class DownloadReadiness:
    ready: bool
    message: str


class ModelDownloadCancelled(RuntimeError):
    """Raised when an operator cancels an optional model download."""


class OllamaManager:
    def __init__(self, endpoint: str = "http://127.0.0.1:11434"):
        self.endpoint = endpoint.rstrip("/")

    def status(self) -> ModelStatus:
        if not shutil.which("ollama"):
            return ModelStatus(False, False, "Ollama is not installed.")
        try:
            payload = self._request("/api/tags")
        except OSError:
            return ModelStatus(False, False, "Ollama is installed but not running.")
        raw_models = payload.get("models", [])
        model_items = raw_models if isinstance(raw_models, list) else []
        models = {
            str(item.get("name", ""))
            for item in model_items if isinstance(item, dict)
        }
        return ModelStatus(True, OLLAMA_MODEL in models, "Ready" if OLLAMA_MODEL in models else "Model not downloaded.")

    def download_readiness(self) -> DownloadReadiness:
        required_disk = OLLAMA_SIZE_BYTES + 1_000_000_000
        if shutil.disk_usage(Path.home()).free < required_disk:
            return DownloadReadiness(False, "At least 4.2 GB of free disk space is required for the optional AI model.")
        memory = _physical_memory_bytes()
        if memory is not None and memory < 8_000_000_000:
            return DownloadReadiness(False, "The optional AI model requires at least 8 GB of system RAM. Continue with OCR/MRZ only.")
        return DownloadReadiness(True, "Enough disk space and memory are available for the optional model.")

    def pull(
        self,
        progress: Callable[[str, int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Download only after an explicit UI confirmation."""
        body = json.dumps({"name": OLLAMA_MODEL, "stream": True}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/api/pull", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                for line in response:
                    if cancelled and cancelled():
                        raise ModelDownloadCancelled("Optional AI model download was cancelled.")
                    item = json.loads(line.decode("utf-8"))
                    if progress:
                        progress(str(item.get("status", "Downloading model")), int(item.get("completed", 0)), int(item.get("total", 0)))
        except urllib.error.URLError as exc:
            raise RuntimeError("Could not download the optional AI model. Check Ollama and your internet connection.") from exc

    def extract_document_fields(self, image: bytes) -> dict[str, str]:
        """Return only a conservative, schema-limited local VLM suggestion."""
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": "Return JSON only with full_name, document_number, nationality, birth_date, sex. Extract only clearly visible identity-document values; use empty strings when uncertain.",
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            f"{self.endpoint}/api/generate", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
            candidate = json.loads(str(result.get("response", "")))
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return {}
        if not isinstance(candidate, dict):
            return {}
        allowed = {"full_name", "document_number", "nationality", "birth_date", "sex"}
        return {key: value.strip().upper() for key, value in candidate.items() if key in allowed and isinstance(value, str) and value.strip()}

    def _request(self, path: str) -> dict[str, object]:
        with urllib.request.urlopen(f"{self.endpoint}{path}", timeout=3) as response:
            decoded = json.loads(response.read().decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {}


def _physical_memory_bytes() -> int | None:
    """Best-effort cross-platform physical-memory detection for a first-run check."""
    try:
        if os.name == "nt":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            success = ctypes.CDLL("kernel32.dll").GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.total_physical) if success else None
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
