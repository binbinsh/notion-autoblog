# upvote module usage

## Purpose

The `upvote` module provides a Hugo upvote component plus an example Cloudflare Worker backend.

## How to include it

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

## Site configuration

```toml
[params.upvote]
  enabled = true
  endpoint = "/api/upvote"
  infoEndpoint = "/api/upvote-info"
```

## Partial

Render it at the bottom of the article page or in the metadata area:

```go-html-template
{{ partial "upvote/widget.html" . }}
```

## Shortcode

To insert it manually in Markdown:

```md
{{< upvote >}}
```

## Backend files

The example Cloudflare Worker lives at:

- `cloudflare/worker.py`
- `cloudflare/wrangler.toml`

Prepare before deploying:

- a KV namespace
- `UPVOTE_COOKIE_SECRET`
