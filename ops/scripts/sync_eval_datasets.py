#!/usr/bin/env python3
"""Sync ops/eval_datasets/*.jsonl into MLflow's dataset tracking.

Note: `mlflow.genai.create_dataset`/`get_dataset` require Unity Catalog and the
`databricks-agents` package (confirmed by testing against a self-hosted OSS
server: it raises ImportError without that package) - not usable here. Instead
this uses the OSS-compatible `mlflow.data` + `log_input` mechanism: each sync
logs the dataset as an input on a run in the `ops-eval-datasets` experiment,
tagged with its content digest, so drift can be detected without Unity Catalog.

Usage:
    python sync_eval_datasets.py --check   # compare local digest against the latest logged run, exit 1 on drift
    python sync_eval_datasets.py --apply   # log a new run for any dataset whose digest differs
"""

import argparse
import json
import pathlib
import sys

import mlflow
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from common.mlflow_client import configure_tracking_uri  # noqa: E402

DATASETS_DIR = pathlib.Path(__file__).resolve().parent.parent / "eval_datasets"
EXPERIMENT_NAME = "ops-eval-datasets"


def load_local_dataframe(path: pathlib.Path) -> pd.DataFrame:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return pd.DataFrame(rows)


def latest_logged_digest(experiment_id: str, dataset_name: str) -> str | None:
    runs = mlflow.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.ops_dataset_name = '{dataset_name}'",
        order_by=["start_time DESC"],
        max_results=1,
    )
    if runs.empty:
        return None
    return runs.iloc[0].get("tags.ops_dataset_digest")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    configure_tracking_uri()
    experiment = mlflow.set_experiment(EXPERIMENT_NAME)

    drifted = []
    for path in sorted(DATASETS_DIR.glob("*.jsonl")):
        name = path.stem
        df = load_local_dataframe(path)
        dataset = mlflow.data.from_pandas(df, source=str(path), name=name)

        remote_digest = latest_logged_digest(experiment.experiment_id, name)
        if remote_digest == dataset.digest:
            print(f"[unchanged] {name} (digest {dataset.digest})")
            continue

        drifted.append(name)
        if args.check:
            print(f"[drift] {name}: local digest {dataset.digest}, last logged {remote_digest}")
            continue

        with mlflow.start_run(
            experiment_id=experiment.experiment_id, run_name=f"sync-{name}"
        ) as run:
            mlflow.log_input(dataset, context="ops-eval-dataset")
            mlflow.set_tag("ops_dataset_name", name)
            mlflow.set_tag("ops_dataset_digest", dataset.digest)
        print(f"[synced] {name} -> digest {dataset.digest} (run {run.info.run_id})")

    if args.check and drifted:
        print(f"\n{len(drifted)} dataset(s) out of sync with the latest logged run.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
