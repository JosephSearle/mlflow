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

# Give mlflow a moment to bind before the proxy starts forwarding to it.
for i in $(seq 1 30); do
  if wget -q -O /dev/null "http://127.0.0.1:${MLFLOW_INTERNAL_PORT}/health" 2>/dev/null; then
    break
  fi
  sleep 1
done

: "${AUTH0_ISSUER_URL:?AUTH0_ISSUER_URL is required unless AUTH_DISABLED=true}"
: "${AUTH0_CLIENT_ID:?AUTH0_CLIENT_ID is required unless AUTH_DISABLED=true}"
: "${AUTH0_CLIENT_SECRET:?AUTH0_CLIENT_SECRET is required unless AUTH_DISABLED=true}"
: "${OAUTH2_PROXY_COOKIE_SECRET:?OAUTH2_PROXY_COOKIE_SECRET is required unless AUTH_DISABLED=true}"
: "${OAUTH2_PROXY_COOKIE_SECURE:=true}"

# Ops scripts (sync_*.py, CI) authenticate with a bearer token from an Auth0
# Machine-to-Machine app instead of a browser session cookie. --extra-jwt-issuers
# tells oauth2-proxy to accept and verify those tokens directly (skipping the
# cookie/login flow) as long as their `aud` claim matches AUTH0_M2M_AUDIENCE -
# the API identifier configured for the M2M app in Auth0. See README for how to
# set that API up and mint tokens.
EXTRA_JWT_ISSUERS_ARGS=""
if [ -n "${AUTH0_M2M_AUDIENCE:-}" ]; then
  EXTRA_JWT_ISSUERS_ARGS="--extra-jwt-issuers=${AUTH0_ISSUER_URL}=${AUTH0_M2M_AUDIENCE}"
fi

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
  --reverse-proxy=true \
  --skip-jwt-bearer-tokens=true \
  $EXTRA_JWT_ISSUERS_ARGS
