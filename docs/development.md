# Development Guide

Multi-tenant Hugo SaaS on Cloudflare. This document covers repo layout, local dev, deployment, and operations.

## Repository Layout

```
workers/
  shared/          TypeScript types, AES-GCM token crypto, ULID, subdomain validation, KV helpers
  edge-serve/      Public site router (Host header -> tenant -> R2 stream + KV cache)
  admin/           Hono + HTMX admin UI (tenant CRUD, Notion bind, theme picker, build audit log)
  build-consumer/  Cloudflare Queue consumer; coalesces builds per tenant; calls container; purges cache
  notion-cron/     5-minute Cron Trigger; enqueues sync+build jobs for active tenants
container/         Docker image (Hugo + Python 3.12 + boto3 + cryptography)
  Dockerfile
  container_server.py     HTTP server dispatching POST /run -> build_runner | sync_runner
  build_runner.py         D1 -> Hugo site -> R2 upload (content-hash revisioning)
  sync_runner.py          Notion -> D1 upsert (reuses scripts/ Python)
  build-and-push.sh       Build & push image to a registry
infra/
  d1/0001_init.sql        Schema: accounts, tenants, posts, themes, builds
  d1/0002_seed_themes.sql Curated theme registry (~25 themes)
themes/                   Vendored Hugo themes (populated by scripts/vendor_themes.py)
scripts/
  vendor_themes.py        Clones curated themes for the container build context
  tracer_publish.py       Phase 1 one-shot site upload + D1 seed
  notion_service.py, hugo_converter.py, media_handler.py, ...   Existing Python reused by sync_runner
docs/                     This guide + architecture + runbooks
examples/gridplanet/      Reference tenant (used by tracer_publish.py)
```

## Local Development

### Prerequisites

- Node 20+ and `pnpm` (or `npm`) for the workers
- `uv` for Python (per AGENTS.md)
- Docker for container builds
- `wrangler` (`npm i -g wrangler@3` or use `npx`)

### Workers

Each worker has its own `package.json`. From the repo root:

```bash
# Install all worker deps
for d in workers/*/; do (cd "$d" && [ -f package.json ] && npm install); done

# Type-check
for d in workers/*/; do (cd "$d" && [ -f tsconfig.json ] && npm run typecheck); done

# Local dev (one worker at a time)
cd workers/admin && npm run dev
```

`wrangler dev` for the admin and edge workers will use a local Miniflare D1/KV/R2 by default. For end-to-end local work you need either remote bindings (`--remote`) or the test harness (below).

### Container

```bash
# Vendor curated themes once (clones into ./themes/)
uv run python scripts/vendor_themes.py

# Build & push image
container/build-and-push.sh ghcr.io/your-org/notion-autoblog-builder:latest
```

The container exposes `POST /run` and accepts a JSON job:

```json
{ "tenant_id": "...", "mode": "build" | "sync" | "sync+build", "reason": "..." }
```

### Tests

Integration tests use Vitest + Miniflare to run workers in-process with mocked D1, KV, R2, and Queues.

```bash
cd workers && npm test
```

See `workers/tests/README.md` for what is covered and the explicit gaps (the container is mocked; real CF deployment is not validated).

The legacy single-tenant Python tests still apply to `scripts/`:

```bash
uv run python -m unittest discover -s tests
```

## Deployment

### One-time setup

1. Create Cloudflare resources:
   ```bash
   wrangler d1 create notion-autoblog
   wrangler kv:namespace create routing
   wrangler r2 bucket create notion-autoblog-sites
   wrangler queues create build-jobs
   ```
2. Apply migrations:
   ```bash
   wrangler d1 migrations apply notion-autoblog --remote
   wrangler d1 execute notion-autoblog --remote --file infra/d1/0002_seed_themes.sql
   wrangler d1 execute notion-autoblog --remote --file infra/d1/0003_post_cell.sql
   wrangler d1 execute notion-autoblog --remote --file infra/d1/0004_apex_seed.sql
   ```
3. Replace `REPLACE_WITH_D1_ID` and `REPLACE_WITH_KV_ID` placeholders across `workers/*/wrangler.toml`.
4. Set secrets:
   ```bash
   wrangler secret put NOTION_TOKEN_KEY --name admin            # 32-byte base64 key for AES-GCM
   wrangler secret put SESSION_SECRET --name admin
   wrangler secret put MAPTILER_KEY --name build-consumer       # MapTiler API key for the apex map
   ```
   Also set the `NOMINATIM_USER_AGENT` var (a [Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/) requirement) on the `admin` worker, e.g.:
   ```bash
   wrangler vars put NOMINATIM_USER_AGENT --name admin "gridpla.net (ops@example.com)"
   ```
5. Build & push the container image; record its registry URL into `workers/build-consumer/wrangler.toml`.

### Per-deploy

```bash
# Workers
for w in shared edge-serve admin build-consumer notion-cron; do
  (cd "workers/$w" && npm run deploy)
done

# Container (when build/sync code changes)
container/build-and-push.sh ghcr.io/your-org/notion-autoblog-builder:$(git rev-parse --short HEAD)
```

The Cloudflare Containers binding in `workers/build-consumer/wrangler.toml` is the boundary that needs adjustment per the current Cloudflare Containers SDK shape — see `docs/architecture.md` "Container binding" section.

### DNS

Wildcard `*.gridpla.net` CNAME -> the edge-serve worker route. The bare apex `gridpla.net` ALSO routes to edge-serve and is served by the synthetic `ten_apex` tenant (the global map). Reserved subdomains (`admin`, `api`, `www`, etc.) are enforced in `workers/shared/src/index.ts`.

## The Apex (Global Map)

`gridpla.net` itself shows a map of every geo-tagged post across all tenants. Architecture:

- D1 row: `tenants` has a synthetic row `id='ten_apex'`, `subdomain='__apex__'`, `theme_id='apex'`, `show_on_global_map=0` (so apex posts don't loop into themselves). Underscores in subdomain make it unclaimable by users.
- Renderer: `workers/build-consumer/src/apex.ts` (TypeScript, no Hugo). Aggregates posts → groups by `cell_id` → writes 4 files (`index.html`, `style.css`, `map.js`, `cells.json`) under `sites/ten_apex/{revision}/` in R2.
- Trigger: every successful per-tenant build sends a `ten_apex` job to `BUILD_QUEUE`. Coalescing in build-consumer dedupes bursty publishes. Apex itself never re-enqueues.
- Privacy: tenants can opt out via the **Privacy** section on their tenant settings page (`tenants.show_on_global_map=0`). No lat/lng is ever stored — only ~5 km² H3 cell ids.
- Edge serving: `workers/edge-serve/src/index.ts` maps the bare apex Host to the `__apex__` subdomain key, which resolves through the same KV/D1 routing as any other tenant.

ADR: `docs/adr/0001-grid-map-design.md`.

## Operations

### Adding or updating a theme

1. Edit `infra/d1/0002_seed_themes.sql` (add row or change `git_ref`).
2. `uv run python scripts/vendor_themes.py --pin` (clones and rewrites with resolved SHA).
3. Rebuild and push the container image.
4. Apply the seed: `wrangler d1 execute notion-autoblog --remote --file infra/d1/0002_seed_themes.sql`.

### Inspecting builds

Per-tenant build history: `https://admin.gridpla.net/tenants/{id}/builds`. The `builds` table records status, duration, revision hash, and error messages.

### Cache layers (top to bottom)

- Cloudflare CDN cache (purged by build-consumer after revision flip)
- KV `routing` namespace (subdomain -> `{tenant_id, current_revision}`)
- R2 (immutable per-revision objects under `sites/{tenant_id}/{revision}/`)
- D1 (canonical post + tenant state)

### Rate limits

Admin worker enforces 60 builds/hour/tenant via KV sliding window. Returning `429` means the operator should wait or raise the limit in `enqueueBuild`.

## What This Repo Is NOT

- Not a single-tenant CLI anymore. The old `notion-autoblog --site-dir ...` flow has been removed; `scripts/` Python is now a library used by `container/sync_runner.py`.
- Not a "publish in <1s end-to-end" system. Author-perceived publish is fast (D1 write + optimistic UI); visitor-perceived publish is 5-15 seconds (Hugo build + R2 upload + cache purge). See `docs/architecture.md` for the honest tradeoff.
- Not validated end-to-end on real Cloudflare yet. The integration test harness mocks the container; real deployment requires the operator's CF account.
