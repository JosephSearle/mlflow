#!/usr/bin/env python3
"""Schema-only validation for ops/gateway/*.yaml. No network access.

Run in CI on every PR touching ops/gateway/.
"""

import pathlib
import sys

import yaml

GATEWAY_DIR = pathlib.Path(__file__).resolve().parent.parent / "gateway"
REQUIRED_FIELDS = {"name", "endpoint_type", "provider", "model"}


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

    if "name" in data and data["name"] != path.stem:
        errors.append(
            f"{path.name}: 'name' ({data['name']!r}) must match the filename stem "
            f"({path.stem!r})"
        )

    if "config" in data:
        config = data["config"]
        if not isinstance(config, dict):
            errors.append(f"{path.name}: 'config' must be a mapping if present")
        else:
            for key, value in config.items():
                if key.endswith("_key") or key.endswith("_secret"):
                    errors.append(
                        f"{path.name}: 'config.{key}' looks like a raw secret; use an "
                        f"'*_env_var' field instead so no credential is committed"
                    )

    return errors


def main() -> int:
    files = sorted(GATEWAY_DIR.glob("*.yaml"))
    if not files:
        print(f"No gateway endpoint files found in {GATEWAY_DIR}")
        return 0

    all_errors = []
    for path in files:
        all_errors.extend(validate_file(path))

    if all_errors:
        print("Gateway config validation failed:")
        for error in all_errors:
            print(f"  - {error}")
        return 1

    print(f"All {len(files)} gateway endpoint file(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
