#!/usr/bin/env python3
"""Schema-only validation for ops/eval_datasets/*.jsonl. No network access.

Run in CI on every PR touching ops/eval_datasets/.
"""

import json
import pathlib
import sys

DATASETS_DIR = pathlib.Path(__file__).resolve().parent.parent / "eval_datasets"


def validate_file(path: pathlib.Path) -> list[str]:
    errors = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number}: invalid JSON: {exc}")
            continue

        if not isinstance(row, dict):
            errors.append(f"{path.name}:{line_number}: row must be a JSON object")
            continue

        if "inputs" not in row:
            errors.append(f"{path.name}:{line_number}: missing 'inputs' field")
        elif not isinstance(row["inputs"], dict):
            errors.append(f"{path.name}:{line_number}: 'inputs' must be an object")

        if "expectations" in row and not isinstance(row["expectations"], dict):
            errors.append(f"{path.name}:{line_number}: 'expectations' must be an object")

    return errors


def main() -> int:
    files = sorted(DATASETS_DIR.glob("*.jsonl"))
    if not files:
        print(f"No dataset files found in {DATASETS_DIR}")
        return 0

    all_errors = []
    for path in files:
        all_errors.extend(validate_file(path))

    if all_errors:
        print("Eval dataset validation failed:")
        for error in all_errors:
            print(f"  - {error}")
        return 1

    print(f"All {len(files)} eval dataset file(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
