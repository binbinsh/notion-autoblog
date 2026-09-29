# Notion Publisher

Multi-tenant Notion-to-Markdown/Hugo/HTML publishing pipeline on Cloudflare.
Each tenant gets a `*.gridpla.net` subdomain backed by a Notion database; posts
are synced every 5 minutes and rendered as static Hugo sites served from R2.

This pipeline lives under `document-engine/pipelines/` because its core
responsibility is document conversion and publication. The historical
`notion-autoblog` CLI, package names, and Cloudflare resource names are kept as
runtime contracts.

## End-User Quick Start

1. Visit `https://admin.gridpla.net` and sign in.
2. Create a new tenant (pick a subdomain, choose a theme).
3. Click **Bind Notion**, paste your Notion integration token and database ID.
4. Wait ~30 seconds for the first sync + build. Your site is live at `https://{your-subdomain}.gridpla.net`.
5. Edit posts in Notion. Changes appear within 5 minutes (or click **Sync now**).

## Documentation

- [Architecture overview](docs/architecture.md)
- [Development guide](docs/development.md)
- [Phase 1 runbook](docs/phase1-runbook.md) — single-tenant tracer for initial deployment
