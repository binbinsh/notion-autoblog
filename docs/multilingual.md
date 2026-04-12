# Multilingual Content and Automatic Translation

## Overview

`notion-autoblog` can generate Hugo multilingual content using Hugo's "translation by filename" convention and can optionally translate content through Cloudflare Workers AI.

- Source and target languages are inferred from Hugo configuration
- In multilingual mode, both the source file and translated files use language suffixes such as `post-title.en.md` and `post-title.zh.md`
- In single-language mode, the source file remains `post-title.md`
- Translation results are cached in `.notion_cache.json`
- Each language variant group gets a stable `translationKey` based on `notion_id`

## Content Paths Derived from Slugs

If a slug contains `/`, the leading segments become Hugo directories.

Examples:

- `post-title` -> `content/post-title.md`
- `/post-title` -> `content/post-title.md`
- `posts/post-title` -> `content/posts/post-title.md`
- `/posts/2024/post-title` -> `content/posts/2024/post-title.md`

The examples above show only the path shape. Actual filenames still depend on the language suffix rules.

## Source Language Resolution

The source language is not auto-detected from the content. It is resolved in this order:

1. `params.translate.sourceLanguage`
2. `defaultContentLanguage`
3. the language with the smallest weight, or the first declared language if weights are absent

Recommendations:

- ensure `params.translate.sourceLanguage` is present in your `languages` map
- keep the source language stable across runs to avoid unnecessary content churn

## Environment Setup

Configure these values through environment variables such as `.env`:

- `CLOUDFLARE_API_TOKEN` for Workers AI
- `CLOUDFLARE_ACCOUNT_ID` for Workers AI

If they are missing, the sync still writes the source-language files and skips AI translation.

Language targets come from Hugo config:

- `params.translate.sourceLanguage` defines the writing/source language
- `defaultContentLanguage` defines the default site language
- `languages` defines the available translation targets

The sync translates into every configured language except the resolved source language.

## Summary Generation

If Workers AI is configured, the sync can also generate a short plain-text summary for each output page and store it in front matter as `summary`.

- source-language pages get their own summary
- translated pages get a summary in the target language
- if summary generation is unavailable, the sync falls back to a deterministic excerpt

The default summary model is `@cf/moonshotai/kimi-k2.5`.

## Hugo Configuration Example

```toml
defaultContentLanguage = "en"
defaultContentLanguageInSubdir = false

[languages]
  [languages.en]
    languageName = "English"
    weight = 1
  [languages.zh]
    languageName = "Chinese"
    weight = 2
  [languages.ja]
    languageName = "Japanese"
    weight = 3

[params.translate]
  sourceLanguage = "zh"
```

This workflow uses Hugo's "translation by filename" convention.
Reference: https://gohugo.io/content-management/multilingual/

## Translation Notice Module

Translated files include these front matter fields:

- `notion_source_language`
- `notion_translation_language`
- `notion_source_path`
- `translationKey`

If you import `modules/translation`, you can render the notice from your page template:

```go-html-template
{{ partial "translation/notice.html" . }}
```

You can also insert the shortcode manually:

```md
{{< translation-note >}}
```

## Translation Cache

Translation cache entries are stored in the `translations` section of `.notion_cache.json`.

The cache key is derived from:

- source title and source body
- target language
- translation model

Any change in those inputs invalidates the cached result and triggers a fresh translation.

Summary cache entries are stored separately in the `summaries` section of `.notion_cache.json`.
