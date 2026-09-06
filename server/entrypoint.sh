#!/usr/bin/env sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${MLFLOW_ARTIFACT_ROOT:?MLFLOW_ARTIFACT_ROOT is required}"
: "${PORT:=8080}"
: "${MLFLOW_INTERNAL_PORT:=5000}"

if [ "${AUTH_DISABLED:-false}" = "true" ]; then
  echo "AUTH_DISABLED=true: exposing MLflow directly on 0.0.0.0:\$PORT, no oauth2-proxy"
  exec mlflow server \
    --backend-store-uri "$DATABASE_URL" \
    --default-artifact-root "$MLFLOW_ARTIFACT_ROOT" \
    --host 0.0.0.0 \
    --port "$PORT"
fi

mlflow server \
  --backend-store-uri "$DATABASE_URL" \
  --default-artifact-root "$MLFLOW_ARTIFACT_ROOT" \
  --host 127.0.0.1 \
  --port "$MLFLOW_INTERNAL_PORT" &
MLFLOW_PID=$!

: "${AUTH0_ISSUER_URL:?AUTH0_ISSUER_URL is required unless AUTH_DISABLED=true}"
: "${AUTH0_CLIENT_ID:?AUTH0_CLIENT_ID is required unless AUTH_DISABLED=true}"
: "${AUTH0_CLIENT_SECRET:?AUTH0_CLIENT_SECRET is required unless AUTH_DISABLED=true}"
: "${OAUTH2_PROXY_COOKIE_SECRET:?OAUTH2_PROXY_COOKIE_SECRET is required unless AUTH_DISABLED=true}"
: "${OAUTH2_PROXY_COOKIE_SECURE:=true}"

# Start oauth2-proxy immediately - do NOT gate this on mlflow's health check.
# Platforms like Vercel require the container to accept TCP connections on
# $PORT within a short startup timeout (as low as 15s). mlflow's first
# Postgres connection (Neon) and oauth2-proxy's own OIDC discovery round-trip
# to Auth0 can easily take longer than that combined, so waiting for mlflow
# to be healthy before starting oauth2-proxy risks missing the platform's
# probe window entirely. oauth2-proxy will simply 502 on proxied requests
# until mlflow answers - that's fine, since it still binds $PORT right away.
exec oauth2-proxy \
  --provider=oidc \
  --oidc-issuer-url="$AUTH0_ISSUER_URL" \
  --client-id="$AUTH0_CLIENT_ID" \
  --client-secret="$AUTH0_CLIENT_SECRET" \
  --cookie-secret="$OAUTH2_PROXY_COOKIE_SECRET" \
  --email-domain="*" \
  --http-address="0.0.0.0:${PORT}" \
  --upstream="http://127.0.0.1:${MLFLOW_INTERNAL_PORT}" \
  --cookie-secure="${OAUTH2_PROXY_COOKIE_SECURE}" \
  --skip-provider-button=true \
  --pass-authorization-header=true \
  --reverse-proxy=true
