# 多语言内容与自动翻译

## 概览
`notion-autoblog` 可以按 Hugo 的“按文件名翻译”规则生成多语言内容，并可选通过 OpenRouter 自动翻译。

- 源语言与翻译语言会根据 Hugo 配置生成。
- 当配置了多语言时，源语言与翻译语言都会写成 `post-title.<lang>.md`。
- 仅配置单语言时，源语言文件仍写为 `post-title.md`。
- 翻译结果会缓存在 `.notion_cache.json`，避免重复翻译。
- 每组语言变体都会写入统一的 `translationKey`（使用 `notion_id`）。

## 基于 slug 的内容路径
若 slug 含有 `/`，第一段作为 section 目录，其余部分作为路径。

示例：
- `post-title` -> `content/post-title.md`
- `/post-title` -> `content/post-title.md`
- `blog/post-title` -> `content/blog/post-title.md`
- `/blog/2024/post-title` -> `content/blog/2024/post-title.md`

示例仅展示路径，实际文件名会根据语言后缀补齐。

## 源语言与文件命名
源语言不做自动检测，按以下优先级确定：

1) Hugo 配置 `params.translate.sourceLanguage`
2) `defaultContentLanguage`
3) 语言列表中权重最小的语言（若未设置权重，则取配置顺序第一个）

- 多语言模式：源语言与翻译语言都会使用后缀，例如 `post-title.en.md`、`post-title.zh.md`。
- 单语言模式：仅生成不带后缀的源语言文件，例如 `post-title.md`。

建议确保 `params.translate.sourceLanguage` 出现在 `languages` 列表中。

## 环境配置
在环境变量中配置（例如 `.env`）：

- `OPENROUTER_API_KEY`：用于 OpenRouter 翻译。

若缺少该变量，同步仍会生成源语言文件，但会跳过翻译。

语言列表来自 Hugo 配置（`hugo config --format json` 的结果）：
- `params.translate.sourceLanguage` 用作默认写作语言
- `defaultContentLanguage` 作为站点默认语言
- `languages` 提供可翻译语言集合
翻译目标为配置语言列表中除源语言之外的语言。

## 本地运行
在 Hugo 站点根目录执行：

```bash
uv pip install notion-autoblog/
uv run notion-autoblog --site-dir .
```

若从 monorepo 根目录驱动 example，可显式指定站点目录：

```bash
uv pip install .
uv run notion-autoblog --site-dir examples/trainsh-blog
```

## Hugo 配置
Hugo 需要匹配的语言配置。示例：

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

此流程使用“按文件名翻译”，Hugo 会基于文件名后缀建立多语言关联。
参考：https://gohugo.io/content-management/multilingual/

## 翻译提示模块
译文页面会写入以下 front matter 字段：

- `notion_source_language`
- `notion_translation_language`
- `notion_source_path`
- `translationKey`

若导入 `modules/translation`，可在主题模板中渲染统一提示：

```go-html-template
{{ partial "notion-translation/notice.html" . }}
```

## GitHub Actions（可选）
若使用提供的工作流模板，请设置：

- Secrets：`OPENROUTER_API_KEY`

## 翻译缓存
翻译缓存存放在 `.notion_cache.json` 的 `translations` 字段。

缓存键基于以下内容生成：
- 源标题与正文
- 目标语言
- 翻译模型

任一项变化都会触发重新翻译并更新缓存。
