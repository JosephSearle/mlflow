#!/usr/bin/env python3
"""Render ops/gateway/*.yaml into a single MLflow AI Gateway config file.

Verified against running MLflow 3.1.1 and 3.16.0 installs: the AI Gateway is
a separate, YAML-config-driven process (`mlflow gateway start --config-path
<file>`), not a database-backed API managed through the tracking server -
`mlflow.deployments.get_deploy_client()` against a tracking server URI 404s,
because the gateway doesn't run inside `mlflow server` at all. So "sync"
here means regenerating the combined config file the gateway process reads
on startup, not pushing changes via an API. To pick up changes, restart (or
send the gateway's reload signal, if running) the `mlflow gateway start`
process pointed at the rendered file.

As of 3.16.0, `mlflow gateway start` prints a FutureWarning: it's being
replaced by a new "UI-based AI Gateway" (endpoints managed dynamically
through the server, no restart needed) - see
https://mlflow.org/docs/latest/genai/governance/ai-gateway/. It still works
today (verified: starts and serves `/health` on 3.16.0), but this
file-render approach is the deprecated path. Re-evaluate once the new
system's actual config/API surface is confirmed hands-on - the public docs
don't yet spell out enough to migrate this script to it responsibly.

Usage:
    python sync_gateway.py --check   # render to a temp file, diff against the last rendered config, exit 1 on drift
    python sync_gateway.py --apply   # write ops/gateway/rendered_config.yaml
"""

import argparse
import os
import pathlib
import sys

import yaml

GATEWAY_DIR = pathlib.Path(__file__).resolve().parent.parent / "gateway"
RENDERED_CONFIG_PATH = GATEWAY_DIR / "rendered_config.yaml"


def load_endpoint_definitions() -> list[dict]:
    endpoints = []
    for path in sorted(GATEWAY_DIR.glob("*.yaml")):
        if path == RENDERED_CONFIG_PATH:
            continue
        data = yaml.safe_load(path.read_text())
        endpoints.append(data)
    return endpoints


def resolve_config(data: dict) -> dict:
    """Turn *_env_var references into real values, read from the environment
    only at render time so secrets never live in the repo or the rendered file
    itself when run in CI with the env var unset (left blank, filled in by the
    process that actually starts the gateway)."""
    resolved = {}
    for key, value in data.get("config", {}).items():
        if key.endswith("_env_var"):
            real_key = key[: -len("_env_var")]
            resolved[real_key] = os.environ.get(value, "")
        else:
            resolved[key] = value
    return resolved


def render(endpoints: list[dict]) -> dict:
    return {
        "endpoints": [
            {
                "name": data["name"],
                "endpoint_type": data["endpoint_type"],
                "model": {
                    "provider": data["provider"],
                    "name": data["model"],
                    "config": resolve_config(data),
                },
            }
            for data in endpoints
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rendered = render(load_endpoint_definitions())
    rendered_yaml = yaml.safe_dump(rendered, sort_keys=False)

    if args.check:
        if not RENDERED_CONFIG_PATH.exists():
            print(f"[missing] {RENDERED_CONFIG_PATH} does not exist yet")
            return 1
        if RENDERED_CONFIG_PATH.read_text() != rendered_yaml:
            print(f"[drift] {RENDERED_CONFIG_PATH} is out of date with ops/gateway/*.yaml")
            return 1
        print(f"[unchanged] {RENDERED_CONFIG_PATH}")
        return 0

    RENDERED_CONFIG_PATH.write_text(rendered_yaml)
    print(f"[synced] wrote {RENDERED_CONFIG_PATH}")
    print("Restart `mlflow gateway start --config-path ops/gateway/rendered_config.yaml` to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
