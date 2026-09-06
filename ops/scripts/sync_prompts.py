#!/usr/bin/env python3
"""Sync ops/prompts/*.yaml into the MLflow Prompt Registry.

Usage:
    python sync_prompts.py --check   # pull registry state, diff against repo, exit 1 on drift
    python sync_prompts.py --apply   # register a new prompt version for any file that differs
"""

import argparse
import pathlib
import sys

import mlflow.genai
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from common.mlflow_client import configure_tracking_uri  # noqa: E402

PROMPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "prompts"


def load_local_prompts() -> dict[str, dict]:
    prompts = {}
    for path in sorted(PROMPTS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        prompts[data["name"]] = data
    return prompts


SYNC_ALIAS = "ops-synced"


def current_registry_template(name: str) -> str | None:
    try:
        version = mlflow.genai.load_prompt(f"prompts:/{name}@{SYNC_ALIAS}")
    except Exception:
        return None
    return version.template


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    configure_tracking_uri()
    local_prompts = load_local_prompts()

    drifted = []
    for name, data in local_prompts.items():
        registry_template = current_registry_template(name)
        if registry_template == data["template"]:
            print(f"[unchanged] {name}")
            continue

        drifted.append(name)
        if args.check:
            print(f"[drift] {name}: repo differs from registry")
            continue

        version = mlflow.genai.register_prompt(
            name=name,
            template=data["template"],
            commit_message=data.get("commit_message", "Synced from ops/prompts"),
            tags=data.get("tags", {}),
        )
        mlflow.genai.set_prompt_alias(name=name, alias=SYNC_ALIAS, version=version.version)
        print(f"[synced] {name} -> version {version.version}")

    if args.check and drifted:
        print(f"\n{len(drifted)} prompt(s) out of sync with the registry.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
