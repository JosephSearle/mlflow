# mlflow

Self-hosted MLflow tracking server deployed to Vercel, behind Auth0 SSO, backed by
Postgres (Neon in production). Includes an "ops" layer for versioning prompts,
AI Gateway model configs, and evaluation datasets, with Copier templates to
scaffold new ones.

- `server/` — the MLflow server container (`Dockerfile.vercel`), fronted by
  `oauth2-proxy` configured against Auth0 OIDC. Deployed to Vercel as a Docker/Fluid
  Compute function; stateless by design (Postgres for metadata, S3-compatible
  storage for artifacts). Human logins go through the normal OIDC/cookie flow;
  scripts and CI authenticate with a bearer token from a separate Auth0
  Machine-to-Machine app instead (see **Authenticating ops scripts** below).
- `ops/` — prompts, AI Gateway endpoint definitions, and eval datasets as
  version-controlled files, with `validate_*.py` (schema-only, no network, run in
  CI) for each, and `ops/templates/` (Copier) to scaffold new ones (see
  **Creating new ops artifacts** below). Each artifact type syncs differently,
  verified against running MLflow 3.1.1 and 3.16.0 servers:
  - **Prompts** (`sync_prompts.py`) push into MLflow's Prompt Registry via
    `mlflow.genai.register_prompt`/`load_prompt` (this reuses the Model Registry
    tables, so it works against the same Postgres-backed server with no extra
    infra).
  - **Eval datasets** (`sync_eval_datasets.py`) log into MLflow's generic dataset
    tracking via `mlflow.data` + `log_input` on a run. Note:
    `mlflow.genai.create_dataset`/`get_dataset` looked like the natural fit but
    actually require Unity Catalog and the `databricks-agents` package — they
    raise `ImportError` against a self-hosted OSS server, so they're not used here.
  - **AI Gateway** (`sync_gateway.py`) renders `ops/gateway/*.yaml` into a single
    `ops/gateway/rendered_config.yaml` (gitignored — it contains resolved secrets).
    The gateway is a separate process from the tracking server
    (`mlflow gateway start --config-path ops/gateway/rendered_config.yaml`), still
    YAML-config-driven rather than API-managed as of MLflow 3.16.0 — there's no
    dynamic "push config" API to sync against yet. **Note:** 3.16.0 prints a
    `FutureWarning` that this CLI is being replaced by a new UI-based AI Gateway
    with dynamic endpoint management. It still works (verified), but is the
    deprecated path — worth revisiting once that system's config/API surface is
    documented well enough to migrate to.
- `docker-compose.yml` — local Postgres + MLflow server, auth disabled, for
  development without touching Neon or Auth0.

## Local development

```bash
cp .env.example .env   # fill in values you need locally
docker compose up
# MLflow UI at http://localhost:5001 (see docker-compose.yml for the port mapping)

pip install -r ops/requirements.txt
python ops/scripts/validate_prompts.py
python ops/scripts/validate_gateway.py
python ops/scripts/validate_eval_datasets.py

export MLFLOW_TRACKING_URI=http://localhost:5001
python ops/scripts/sync_prompts.py --check
python ops/scripts/sync_prompts.py --apply
python ops/scripts/sync_eval_datasets.py --apply

# Gateway config is rendered locally, not pushed over the network:
export OPENAI_API_KEY=sk-...
python ops/scripts/sync_gateway.py --apply
mlflow gateway start --config-path ops/gateway/rendered_config.yaml
```

## Creating new ops artifacts

Each artifact type has a Copier template under `ops/templates/` that scaffolds a
new file with the right shape, so you don't have to remember the schema by hand:

```bash
# New prompt -> ops/prompts/<name>.yaml
copier copy ops/templates/prompt ops/prompts

# New AI Gateway endpoint -> ops/gateway/<name>.yaml
copier copy ops/templates/gateway_endpoint ops/gateway

# New eval dataset -> ops/eval_datasets/<name>.jsonl
copier copy ops/templates/eval_dataset ops/eval_datasets
```

Each asks a few questions (name, owning team, provider, etc.) and writes exactly
one new file into the target folder — it won't touch other files already there.
Fill in the `TODO` placeholders it leaves behind, then run the matching
`validate_*.py` and `sync_*.py --apply`. Re-running a template's `copier copy`
command against the same destination later (e.g. after editing the template
itself) will offer to update that one file, using the `.copier-answers.<name>.yml`
file it writes alongside it to recall your answers.

## Authenticating ops scripts

Human logins to the deployed server go through Auth0's normal browser OIDC flow.
Scripts (`sync_*.py`, CI) have no browser, so they authenticate with a bearer
token instead, via a separate Auth0 Machine-to-Machine app:

1. In Auth0: **Applications → APIs**, create an API (its "Identifier" becomes
   `AUTH0_M2M_AUDIENCE`).
2. **Applications → Create Application → Machine to Machine**, authorize it for
   that API. Note its Client ID/Secret as `AUTH0_M2M_CLIENT_ID`/`AUTH0_M2M_CLIENT_SECRET`.
3. Set `AUTH0_M2M_AUDIENCE` on the deployed server too (it's read by
   `entrypoint.sh` to tell `oauth2-proxy` which token audience to trust via
   `--extra-jwt-issuers`, verified to parse and trigger OIDC discovery correctly;
   full token validation depends on your real Auth0 tenant).
4. Before running sync scripts against a deployed (non-local) server:
   ```bash
   export MLFLOW_TRACKING_TOKEN="$(./ops/scripts/get_tracking_token.sh)"
   ```
   Tokens are short-lived (Auth0 default: 24h) — mint a fresh one per CI run
   rather than storing it as a long-lived secret.

## Production

Set `DATABASE_URL` to the Neon connection string, `MLFLOW_ARTIFACT_ROOT` to an
`s3://` URI, and the `AUTH0_*` / `OAUTH2_PROXY_COOKIE_SECRET` env vars in the
Vercel project, then deploy `server/Dockerfile.vercel`. See `.env.example` for
the full list.

## CI

`.github/workflows/ci.yml` runs on every PR and push to `main`:

- `validate-prompts` / `validate-gateway` / `validate-eval-datasets` — the same
  schema-only `validate_*.py` scripts from local dev, no network.
- `docker-build` — builds `server/Dockerfile.vercel` to catch a broken image
  before it reaches Vercel.
- `sync-integration` — brings up the real `docker-compose.yml` stack (Postgres +
  MLflow, `AUTH_DISABLED=true` since there's no Auth0 tenant in CI) and runs
  `sync_*.py --apply` then `--check` against it, exactly as verified by hand
  during development — this is the check that would catch an MLflow API/behavior
  regression the schema validators can't see.
- `secret-scan` — `detect-secrets` against `.secrets.baseline`, failing the
  build if a new/unaudited secret shows up. To update the baseline after adding
  an intentional entry (or a new plugin), run locally and commit the diff:
  ```bash
  pip install detect-secrets
  detect-secrets scan --exclude-files '\.git/' --exclude-files 'ops/gateway/rendered_config\.yaml' --baseline .secrets.baseline
  ```
