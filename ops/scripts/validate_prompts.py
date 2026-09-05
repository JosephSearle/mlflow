#!/usr/bin/env python3
"""Schema-only validation for ops/prompts/*.yaml. No network access.

Run in CI on every PR touching ops/prompts/.
"""

import pathlib
import sys

import yaml

PROMPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "prompts"
REQUIRED_FIELDS = {"name", "template"}


def validate_file(path: pathlib.Path) -> list[str]:
    errors = []
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [f"{path.name}: invalid YAML: {exc}"]

    if not isinstance(data, dict):
        return [f"{path.name}: top-level content must be a mapping"]

    missing = REQUIRED_FIELDS - data.keys()
    if missing:
        errors.append(f"{path.name}: missing required field(s): {sorted(missing)}")

    if "name" in data and not isinstance(data["name"], str):
        errors.append(f"{path.name}: 'name' must be a string")

    if "template" in data and not isinstance(data["template"], str):
        errors.append(f"{path.name}: 'template' must be a string")

    if "tags" in data and not isinstance(data["tags"], dict):
        errors.append(f"{path.name}: 'tags' must be a mapping if present")

    if "name" in data and data["name"] != path.stem:
        errors.append(
            f"{path.name}: 'name' ({data['name']!r}) must match the filename stem "
            f"({path.stem!r})"
        )

    return errors


def main() -> int:
    files = sorted(PROMPTS_DIR.glob("*.yaml"))
    if not files:
        print(f"No prompt files found in {PROMPTS_DIR}")
        return 0

    all_errors = []
    for path in files:
        all_errors.extend(validate_file(path))

    if all_errors:
        print("Prompt validation failed:")
        for error in all_errors:
            print(f"  - {error}")
        return 1

    print(f"All {len(files)} prompt file(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
