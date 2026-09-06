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

: "${AUTH0_ISSUER_URL:?AUTH0_ISSUER_URL is required unless AUTH_DISABLED=true}"
: "${AUTH0_CLIENT_ID:?AUTH0_CLIENT_ID is required unless AUTH_DISABLED=true}"
: "${AUTH0_CLIENT_SECRET:?AUTH0_CLIENT_SECRET is required unless AUTH_DISABLED=true}"
: "${OAUTH2_PROXY_COOKIE_SECRET:?OAUTH2_PROXY_COOKIE_SECRET is required unless AUTH_DISABLED=true}"
: "${OAUTH2_PROXY_COOKIE_SECURE:=true}"

# The single, permanent front-door URL for this deployment - used to pin
# oauth2-proxy's OAuth redirect_uri so it never depends on the incoming
# request's Host header. Vercel gives every deployment its own permanent
# hash-suffixed URL (changes on every deploy - it's a per-build debug/rollback
# link, not meant to be the front door) in addition to the project's stable
# Production Domain. VERCEL_PROJECT_PRODUCTION_URL is Vercel's own system env
# var for that stable domain: always set at runtime (even on preview
# deployments), no protocol prefix, and it tracks whatever domain is actually
# assigned as Production - including a custom domain added later - with no
# per-deploy or per-project config needed. It only requires the "Enable
# access to System Environment Variables" checkbox in the Vercel project's
# Environment Variables settings (a one-time toggle, not a value to
# maintain). PUBLIC_URL, if set explicitly, always wins - this is how local
# dev (docker-compose, no Vercel vars present) points this at localhost.
: "${PUBLIC_URL:=${VERCEL_PROJECT_PRODUCTION_URL:+https://$VERCEL_PROJECT_PRODUCTION_URL}}"
: "${PUBLIC_URL:?PUBLIC_URL is required (explicitly, or via Vercel's VERCEL_PROJECT_PRODUCTION_URL - see README) unless AUTH_DISABLED=true}"
PUBLIC_URL="${PUBLIC_URL%/}"

# MLflow has its own, separate DNS-rebinding protection: the Werkzeug server
# underneath `mlflow server` rejects any request whose Host header isn't
# localhost, a private IP, or explicitly allow-listed via --allowed-hosts /
# MLFLOW_SERVER_ALLOWED_HOSTS - with "Invalid Host header - possible DNS
# rebinding attack detected". oauth2-proxy's passHostHeader defaults to true,
# so MLflow sees the *original external* Host header (e.g. the Vercel
# domain), not 127.0.0.1 - this is unrelated to, and not fixed by, the OAuth
# redirect_uri pinning above. Defaults to PUBLIC_URL's own host so it never
# needs separate/manual maintenance; set MLFLOW_SERVER_ALLOWED_HOSTS
# explicitly (comma-separated, wildcards supported, see README) to allow
# further hosts.
PUBLIC_URL_HOST="${PUBLIC_URL#*://}"
PUBLIC_URL_HOST="${PUBLIC_URL_HOST%%/*}"
: "${MLFLOW_SERVER_ALLOWED_HOSTS:=$PUBLIC_URL_HOST}"

mlflow server \
  --backend-store-uri "$DATABASE_URL" \
  --default-artifact-root "$MLFLOW_ARTIFACT_ROOT" \
  --host 127.0.0.1 \
  --port "$MLFLOW_INTERNAL_PORT" \
  --allowed-hosts="$MLFLOW_SERVER_ALLOWED_HOSTS" &
MLFLOW_PID=$!

# Auth0's issuer claim (in its discovery doc and in every token it issues)
# always has exactly one trailing slash - confirmed by testing: passing
# --oidc-issuer-url without it makes discovery fail with "issuer did not
# match the issuer returned by provider" even before the --skip-oidc-discovery
# fix below, and would equally break token/cookie validation with it. Endpoint
# paths built from AUTH0_ISSUER_URL_TRIMMED must NOT have the slash, or they'd
# end up with "//".
AUTH0_ISSUER_URL="${AUTH0_ISSUER_URL%/}"
AUTH0_ISSUER_URL_TRIMMED="$AUTH0_ISSUER_URL"
AUTH0_ISSUER_URL="${AUTH0_ISSUER_URL}/"

# Ops scripts (sync_*.py, CI) authenticate with a bearer token from an Auth0
# Machine-to-Machine app instead of a browser session cookie. --extra-jwt-issuers
# tells oauth2-proxy to accept and verify those tokens directly (skipping the
# cookie/login flow) as long as their `aud` claim matches AUTH0_M2M_AUDIENCE -
# the API identifier configured for the M2M app in Auth0. See README.
# NOTE (residual risk, tested): unlike the main provider, oauth2-proxy has no
# --skip-oidc-discovery equivalent for --extra-jwt-issuers - it always does its
# own "Performing OIDC Discovery..." network round-trip to AUTH0_ISSUER_URL at
# startup, even with --skip-oidc-discovery=true set above. Measured at ~1s
# against the real tenant, comfortably under Vercel's 15s startup timeout, but
# it's a real network dependency this script cannot remove - if Auth0 is slow
# or unreachable, this specific call could still blow the startup window.
EXTRA_JWT_ISSUERS_ARGS=""
if [ -n "${AUTH0_M2M_AUDIENCE:-}" ]; then
  EXTRA_JWT_ISSUERS_ARGS="--extra-jwt-issuers=${AUTH0_ISSUER_URL}=${AUTH0_M2M_AUDIENCE}"
fi

# oauth2-proxy performs OIDC discovery (a network round-trip to
# ${AUTH0_ISSUER_URL}/.well-known/openid-configuration) SYNCHRONOUSLY before
# it binds its listener - confirmed by testing: on a bad/unreachable issuer it
# errors out before ever binding $PORT, and on a slow one it simply doesn't
# bind $PORT until discovery finishes, no matter how it's ordered in this
# script. That's fatal on Vercel, which requires the container to accept TCP
# connections on $PORT within a 15s startup timeout - so --skip-oidc-discovery
# with Auth0's standard (non-discovered) endpoint paths is required, not
# optional, here.
exec oauth2-proxy \
  --provider=oidc \
  --oidc-issuer-url="$AUTH0_ISSUER_URL" \
  --skip-oidc-discovery=true \
  --login-url="${AUTH0_ISSUER_URL_TRIMMED}/authorize" \
  --redeem-url="${AUTH0_ISSUER_URL_TRIMMED}/oauth/token" \
  --oidc-jwks-url="${AUTH0_ISSUER_URL_TRIMMED}/.well-known/jwks.json" \
  --profile-url="${AUTH0_ISSUER_URL_TRIMMED}/userinfo" \
  --client-id="$AUTH0_CLIENT_ID" \
  --client-secret="$AUTH0_CLIENT_SECRET" \
  --redirect-url="${PUBLIC_URL}/oauth2/callback" \
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
