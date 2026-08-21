#!/usr/bin/env python3
"""Private acceptance check for the local MIO documents.

The documents contain personal information. They are never added to source
control and this command reports only an anonymous name hash and quality flags.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import monotonic

from crewlisterpro.ocr import LocalOCR, load_image


def verify(corpus: Path, manifest_path: Path, minimum_valid_mrz: int) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    fixtures = sorted(path for path in corpus.iterdir() if path.is_file())
    if not fixtures:
        print("No private documents found.", file=sys.stderr)
        return 2
    failures = 0
    valid_mrz = 0
    for source in fixtures:
        fixture = hashlib.sha256(source.name.encode("utf-8")).hexdigest()[:12]
        started = monotonic()
        try:
            result = LocalOCR().extract(load_image(source.read_bytes(), source.name))
            expected = manifest.get(fixture, {}).get("checksum_valid_mrz")
            matched = expected is None or expected == result.mrz_valid
            failures += int(not matched)
            valid_mrz += int(result.mrz_valid)
            print({"fixture": fixture, "rendered": True, "checksum_valid_mrz": result.mrz_valid, "risk": result.risk_level, "seconds": round(monotonic() - started, 1), "expected_match": matched})
        except (OSError, ValueError, RuntimeError) as exc:
            failures += 1
            print({"fixture": fixture, "rendered": False, "error": type(exc).__name__})
    if failures or valid_mrz < minimum_valid_mrz:
        print(f"Acceptance failed: {failures} fixture failures; {valid_mrz} valid MRZ documents.", file=sys.stderr)
        return 1
    print(f"Acceptance passed: {len(fixtures)} documents; {valid_mrz} checksum-valid MRZ results.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path(__file__).resolve().parents[2] / "MIO")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "tests" / "private_mio_manifest.json")
    parser.add_argument("--minimum-valid-mrz", type=int, default=4)
    raise SystemExit(verify(**vars(parser.parse_args())))
