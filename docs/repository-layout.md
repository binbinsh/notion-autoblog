# Repository Layout

## Current Structure

This repository is organized as a product repository with an embedded example site:

```text
.
├── modules/
├── scripts/
├── templates/
├── docs/
└── examples/
    └── trainsh-blog/
```

## Root Responsibilities

- the root repository provides the `notion-autoblog` Python package
- `modules/` contains reusable Hugo Modules, currently `translation` and `upvote`
- `scripts/` contains the sync, translation, summary, and conversion pipeline
- `templates/` contains reusable CI/CD workflow templates
- `docs/` contains detailed product and implementation documentation

## Example Site

`examples/trainsh-blog/` is the Hugo example site used by this project.

It contains:

- Hugo configuration
- a Cloudflare deployment configuration for the example site
- the `hugo-trainsh` theme as a git submodule
- local `layouts/` overrides used to wire repository-provided modules into the site

## Repository-Owned Publishing Flow

The root `.github/workflows/deploy-cloudflare.yml` workflow:

1. installs `notion-autoblog` from the repository root
2. syncs Notion content into `examples/trainsh-blog/`
3. builds the example site
4. deploys the result to Cloudflare

This keeps the package code, example site, and deployment workflow in a single repository.
