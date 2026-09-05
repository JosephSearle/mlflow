"""Shared MLflow client setup for ops scripts.

All sync/validate scripts read MLFLOW_TRACKING_URI from the environment so the
same script works against a local docker-compose server or the deployed one.

Against a deployed server, the tracking URI is fronted by oauth2-proxy, which
has no session cookie to check for a script (there's no browser). Auth for
that case is a bearer token from an Auth0 Machine-to-Machine app, read from
MLFLOW_TRACKING_TOKEN - MLflow's REST client picks this env var up on its own
and sends it as `Authorization: Bearer <token>` on every request, so no
explicit wiring is needed here beyond making sure it's set when talking to a
non-local server. See README for how to set up the M2M app and mint a token
(ops/scripts/get_tracking_token.sh).
"""

import os

import mlflow


def configure_tracking_uri() -> str:
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        raise SystemExit(
            "MLFLOW_TRACKING_URI is not set. Point it at a running MLflow server, "
            "e.g. http://localhost:5000 for docker-compose."
        )

    is_local = "localhost" in tracking_uri or "127.0.0.1" in tracking_uri
    if not is_local and not os.environ.get("MLFLOW_TRACKING_TOKEN"):
        print(
            "warning: MLFLOW_TRACKING_TOKEN is not set and MLFLOW_TRACKING_URI "
            "looks non-local; requests will likely be redirected to the Auth0 "
            "login page instead of reaching the API. Run "
            "ops/scripts/get_tracking_token.sh and export the result.",
        )

    mlflow.set_tracking_uri(tracking_uri)
    return tracking_uri
