"""Synthetic pre-S08 probes. Exit 1 while any confirmed privacy gap remains.

Run with windows/.venv/Scripts/python.exe docs/review_privacy_probes.py.
Print only case identifiers and metadata-field names, never fixture content.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
sys.path.insert(0, str(ROOT / "windows" / "tests"))
from privacy_cases import known_gap_results


def main():
    results = known_gap_results()
    for name, fields in results.items():
        print(f"{name}: {'FAIL' if fields else 'PASS'}" +
              (" (unsafe fields: " + ", ".join(fields) + ")" if fields else ""))
    return int(any(results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
