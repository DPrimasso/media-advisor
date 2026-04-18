"""Validation/migration script for existing JSON files.

Loads all channels/*.json, data/transcripts/**/*.json, data/analysis/**/*.json and
validates them against the Pydantic models. Prints a summary of any schema
drift so it can be fixed before the Python pipeline takes over.

Usage:
    python -m media_advisor.validate
    python -m media_advisor.validate --fix       # attempt to auto-coerce where possible
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from media_advisor.config import Settings
from media_advisor.io.paths import ANALYSIS_DIR, DATA_DIR, TRANSCRIPTS_DIR
from media_advisor.models.analysis import AnalysisResult
from media_advisor.models.channels import ChannelsConfig
from media_advisor.models.pending import PendingResult
from media_advisor.models.transcript import TranscriptResponse


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_file(path: Path, model: type, fix: bool) -> bool:
    try:
        raw = _load(path)
        model.model_validate(raw)
        return True
    except ValidationError as e:
        print(f"  FAIL  {path}")
        for err in e.errors():
            loc = " -> ".join(str(l) for l in err["loc"])
            print(f"        [{loc}] {err['msg']}")
        if fix:
            print(f"        (auto-fix not yet implemented for {model.__name__})")
        return False
    except Exception as e:
        print(f"  ERROR {path}: {e}")
        return False


def run_validation(root: Path, fix: bool = False) -> int:
    """Validate all JSON files. Returns number of failures."""
    failures = 0
    channels_dir = root / "channels"
    analysis_dir = root / DATA_DIR / ANALYSIS_DIR
    transcripts_dir = root / DATA_DIR / TRANSCRIPTS_DIR

    # channels/channels.json
    print("\n=== channels/channels.json ===")
    p = channels_dir / "channels.json"
    if p.exists():
        ok = _validate_file(p, ChannelsConfig, fix)
        if not ok:
            failures += 1
    else:
        print(f"  NOT FOUND: {p}")

    # channels/pending.json
    print("\n=== channels/pending.json ===")
    p = channels_dir / "pending.json"
    if p.exists():
        ok = _validate_file(p, PendingResult, fix)
        if not ok:
            failures += 1
    else:
        print(f"  NOT FOUND: {p}")

    # channel video lists
    print("\n=== channel video lists ===")
    for json_path in sorted(channels_dir.glob("*.json")):
        if json_path.name in ("channels.json", "pending.json"):
            continue
        try:
            raw = _load(json_path)
            if not isinstance(raw, list):
                print(f"  FAIL  {json_path}: expected list, got {type(raw).__name__}")
                failures += 1
            elif not all(isinstance(x, str) for x in raw):
                print(f"  FAIL  {json_path}: list items must be strings")
                failures += 1
            else:
                print(f"  ok    {json_path} ({len(raw)} URLs)")
        except Exception as e:
            print(f"  ERROR {json_path}: {e}")
            failures += 1

    # transcripts
    print("\n=== transcripts ===")
    t_ok = t_fail = 0
    if transcripts_dir.exists():
        for json_path in sorted(transcripts_dir.glob("*/*.json")):
            ok = _validate_file(json_path, TranscriptResponse, fix)
            if ok:
                t_ok += 1
            else:
                t_fail += 1
                failures += 1
    print(f"  {t_ok} ok, {t_fail} failed")

    # analysis
    print("\n=== analysis ===")
    a_ok = a_fail = 0
    if analysis_dir.exists():
        for json_path in sorted(p for p in analysis_dir.glob("*/*.json")
                                if not p.name.startswith("_")):
            ok = _validate_file(json_path, AnalysisResult, fix)
            if ok:
                a_ok += 1
            else:
                a_fail += 1
                failures += 1
    print(f"  {a_ok} ok, {a_fail} failed")

    print(f"\n{'=' * 40}")
    if failures == 0:
        print("All files valid.")
    else:
        print(f"{failures} file(s) failed validation.")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate existing JSON files against Pydantic models")
    parser.add_argument("--root", default=".", help="Project root directory (default: .)")
    parser.add_argument("--fix", action="store_true", help="Attempt to auto-coerce invalid files")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    failures = run_validation(root, fix=args.fix)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
