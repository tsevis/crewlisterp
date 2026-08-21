# CrewListr Pro for Windows and Linux

CrewListr Pro is the companion desktop application for preparing reviewed crew lists without sending identity documents to a cloud service.

Model sizing and hardware rationale are in [`../MODEL_SELECTION.md`](../MODEL_SELECTION.md).

## Security model

- The app asks for a master passphrase before opening local data.
- Records are stored in a SQLCipher database and document originals are encrypted with AES-GCM-derived Fernet keys.
- The passphrase is never persisted. Do not lose it: the encrypted data cannot be recovered.
- AI is optional and only runs after a user confirms its first-run model download.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy crewlisterpro
```

On Windows use `.venv\\Scripts\\python` in place of `.venv/bin/python`.

Install `pyinstaller` before packaging. `scripts/build-windows.ps1` creates a standalone bundle and, when Inno Setup is installed, a Windows installer. `scripts/build-linux.sh` creates a standalone Linux bundle and, when `appimagetool` is installed, an AppImage. Both include the Python runtime and prompt for the optional Ollama `qwen2.5vl:3b` model only when needed.
