# upvote Module

## Purpose

This module provides a reusable upvote widget for Hugo sites, plus an example Cloudflare Worker backend.

It supports two integration styles:

- partials for template-level integration
- a shortcode for manual insertion in Markdown content

## Import

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

## Site Configuration

Enable the widget in your Hugo config:

```toml
[params]
  [params.upvote]
    enabled = true
    endpoint = "/api/upvote"
    infoEndpoint = "/api/upvote-info"
```

## Partial Integration

Render the widget from your page or footer template:

```go-html-template
{{ partial "upvote/widget.html" . }}
```

## Shortcode Integration

Insert the widget directly in Markdown:

```md
{{< upvote >}}
```

## Cloudflare Worker

The backend example lives in:

- `cloudflare/worker.py`
- `cloudflare/wrangler.toml`

Create a KV namespace and configure `UPVOTE_COOKIE_SECRET` before deploying the worker.
