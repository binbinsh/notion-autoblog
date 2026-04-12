# notion-autoblog

Sync Notion content into Hugo using the latest Notion API and a block-based local Markdown conversion pipeline. The repository also ships reusable Hugo modules for translation notices and upvotes.

## Quick Start

### Prerequisites

- Python 3.10+
- Hugo Extended
- Go 1.18+ if you want to use the bundled Hugo Modules
- A Notion Integration with access to your target database/data source

### Install

Run this from your Hugo site root:

```bash
git submodule add https://github.com/binbinsh/notion-autoblog notion-autoblog
git submodule update --init --recursive
uv venv --python 3.10
uv pip install notion-autoblog/
```

If you also want the example theme:

```bash
git submodule add https://github.com/binbinsh/hugo-trainsh.git themes/hugo-trainsh
```

### Optional: Initialize Hugo Modules

If you want to use the bundled translation and upvote modules:

```bash
hugo mod init example.com/your-site
```

Then add this to your Hugo config:

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/translation -> ../notion-autoblog/modules/translation,github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/translation"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

The relative paths above assume:

- your site uses the default `themes/` directory
- `notion-autoblog/` is mounted as a submodule under the site root

If your theme is also a git submodule, keep the theme clean and wire the modules from the site's own `layouts/` overrides instead of editing the theme directly.

### Environment Variables

Required:

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

Optional:

- `CLOUDFLARE_API_TOKEN` for Workers AI
- `CLOUDFLARE_ACCOUNT_ID` for Workers AI
- `CLOUDFLARE_TRANSLATION_MODEL` to override the translation model
- `CLOUDFLARE_SUMMARY_MODEL` to override the summary model
- `HUGO_SITE_DIR` to override the Hugo site root
- `HUGO_CONTENT_DIR` to override the content output directory
- `HUGO_STATIC_DIR` to override the static asset output directory
- `NOTION_CACHE_FILE` to override the cache file path

### Run Sync

From the Hugo site root:

```bash
uv run notion-autoblog --site-dir .
```

From another directory:

```bash
uv run notion-autoblog --site-dir /absolute/path/to/site
```

### Output

- Slugs are treated as Hugo paths
- `posts/post-title` becomes `content/posts/post-title.md`
- if `params.notion.contentSection = "posts"` is set, synced posts are written under `content/posts/`
- Images, videos, audio files, and generic files are downloaded into `static/images/`, `static/videos/`, `static/audios/`, and `static/files/`
- The cache defaults to `.notion_cache.json` at the site root
- Page content is fetched from Notion block children endpoints and converted locally to Markdown
- summaries can be generated automatically and stored in front matter as `summary`

## Shortcodes

The bundled Hugo modules add these shortcodes:

- `{{< translation-note >}}`
- `{{< upvote >}}`

## Default AI Model

As of April 12, 2026, the repository defaults to this Cloudflare Workers AI model:

- Translation: `@cf/moonshotai/kimi-k2.5`
- Summary: `@cf/moonshotai/kimi-k2.5`

Reference:

- [Cloudflare Workers AI - Kimi K2.5](https://developers.cloudflare.com/workers-ai/models/kimi-k2.5/)
- [Cloudflare Workers AI - OpenAI compatibility](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/)

## Documentation

- [Multilingual Workflow](docs/multilingual.md)
- [Hugo Modules](docs/hugo-modules.md)
- [Repository Layout](docs/repository-layout.md)
