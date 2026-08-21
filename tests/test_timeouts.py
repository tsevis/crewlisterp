import subprocess

from PIL import Image

from crewlisterpro.ocr import LocalOCR


def test_ocr_timeout_falls_back_without_raising(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired("tesseract", 1)

    monkeypatch.setattr("crewlisterpro.ocr.subprocess.run", timeout)
    result = LocalOCR(tesseract="tesseract", timeout_seconds=1).extract(Image.new("RGB", (100, 200), "white"))
    assert result.risk_level == "review"
    assert not result.mrz_valid
