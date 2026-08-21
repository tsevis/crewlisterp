import io
import urllib.error
from typing import Self

import pytest

from crewlisterpro.models import ModelDownloadCancelled, OllamaManager


def test_status_is_clear_when_ollama_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("crewlisterpro.models.shutil.which", lambda _name: None)
    status = OllamaManager().status()
    assert not status.runtime_available
    assert not status.model_present


def test_pull_reports_offline_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("crewlisterpro.models.urllib.request.urlopen", offline)
    with pytest.raises(RuntimeError, match="Could not download"):
        OllamaManager().pull()


def test_pull_honours_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response(io.BytesIO):
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("crewlisterpro.models.urllib.request.urlopen", lambda *_args, **_kwargs: Response(b'{"status":"downloading"}\n'))
    with pytest.raises(ModelDownloadCancelled):
        OllamaManager().pull(cancelled=lambda: True)


def test_download_readiness_blocks_low_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    class DiskUsage:
        free = 1

    monkeypatch.setattr("crewlisterpro.models.shutil.disk_usage", lambda _path: DiskUsage())
    readiness = OllamaManager().download_readiness()
    assert not readiness.ready


def test_vlm_rejects_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response(io.BytesIO):
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("crewlisterpro.models.urllib.request.urlopen", lambda *_args, **_kwargs: Response(b'{"response":"not-json"}'))
    assert OllamaManager().extract_document_fields(b"image") == {}
