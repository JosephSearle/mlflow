#!/usr/bin/env sh
# Mints a short-lived Auth0 M2M access token for the ops sync scripts to use
# as MLFLOW_TRACKING_TOKEN against a deployed (non-local) MLflow server.
#
# Requires an Auth0 Machine-to-Machine application authorized for an API whose
# identifier matches AUTH0_M2M_AUDIENCE (see README for setup). The token is
# short-lived (Auth0 default: 24h) - re-run this before each CI job rather than
# storing the output as a long-lived secret.
#
# Usage:
#   export MLFLOW_TRACKING_TOKEN="$(./ops/scripts/get_tracking_token.sh)"
set -eu

: "${AUTH0_ISSUER_URL:?AUTH0_ISSUER_URL is required}"
: "${AUTH0_M2M_CLIENT_ID:?AUTH0_M2M_CLIENT_ID is required}"
: "${AUTH0_M2M_CLIENT_SECRET:?AUTH0_M2M_CLIENT_SECRET is required}"
: "${AUTH0_M2M_AUDIENCE:?AUTH0_M2M_AUDIENCE is required}"

response=$(curl -sS --fail-with-body -X POST "${AUTH0_ISSUER_URL%/}/oauth/token" \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"${AUTH0_M2M_CLIENT_ID}\",\"client_secret\":\"${AUTH0_M2M_CLIENT_SECRET}\",\"audience\":\"${AUTH0_M2M_AUDIENCE}\",\"grant_type\":\"client_credentials\"}")

# Deliberately no external JSON tool dependency - this is a small, fixed shape response.
token=$(printf '%s' "$response" | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')

printf '%s' "$token"
