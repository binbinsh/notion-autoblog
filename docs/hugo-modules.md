# Hugo Modules

## Available Modules

This repository currently provides two reusable Hugo Modules:

- `modules/translation`
- `modules/upvote`

They expose these shortcodes:

- `{{< translation-note >}}`
- `{{< upvote >}}`

## Prerequisite

Initialize Hugo Modules in your site first:

```bash
hugo mod init example.com/your-site
```

## Local Submodule Setup

If your site layout looks like this:

```text
your-site/
├── themes/
└── notion-autoblog/
```

add this to your Hugo config:

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/translation -> ../notion-autoblog/modules/translation,github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/translation"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

Notes:

- `replacements` are resolved relative to `themesDir`
- by default, `themesDir` is `<site>/themes`

## When the Theme Is Also a Git Submodule

If `themes/hugo-trainsh/` or another theme directory is itself a git submodule, keep the theme repository clean and wire the modules from the site's own `layouts/` overrides.

Recommended approach:

- let the theme stay theme-only
- add local template overrides in the site repository
- call the module partials from those overrides

Example:

```go-html-template
{{ partial "translation/notice.html" . }}
{{ partial "upvote/widget.html" . }}
```

## Translation Module

Purpose:

- render a consistent machine-translation notice for translated pages

Shortcode:

```md
{{< translation-note >}}
```

Recommended partial integration:

```go-html-template
{{ partial "translation/notice.html" . }}
```

Module docs:

- `modules/translation/docs/usage.md`

## Upvote Module

Purpose:

- render an upvote widget on article pages
- provide a Cloudflare Worker backend example

Shortcode:

```md
{{< upvote >}}
```

Recommended partial integration:

```go-html-template
{{ partial "upvote/widget.html" . }}
```

Module docs:

- `modules/upvote/docs/usage.md`
