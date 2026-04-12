# notion-autoblog

Sync a Notion database into a Hugo site, generate optional AI summaries and multilingual pages with Cloudflare Workers AI, and ship the result with the bundled translation and upvote Hugo extensions plus the example deployment workflow.

## Quick Start

1. Clone the repository and initialize submodules.
2. Install the package with `uv`.
3. Set `NOTION_TOKEN` and `NOTION_DATABASE_ID`.
4. Run `uv run notion-autoblog --site-dir /absolute/path/to/your/hugo-site`.

## Example Site

The repository includes `examples/trainsh-blog/` as the maintained reference site and `.github/workflows/deploy-cloudflare.yml` as the working deployment workflow.

## Documentation

- [Usage and configuration](docs/usage.md)
- [Hugo modules](docs/modules.md)
- [Development and deployment](docs/development.md)
