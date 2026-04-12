# 使用与配置

## 项目定位

`notion-autoblog` 会读取 Notion 数据库中的已发布文章，拉取 block 内容，转换为本地 Hugo 内容文件，并按需生成：

- 多语言页面
- 页面摘要
- 本地静态资源
- 示例站点的 Cloudflare 部署产物

当前仓库本身就是可复用模板，维护重点是根目录 Python 包、`examples/trainsh-blog/` 示例站点，以及根目录 GitHub Actions workflow。

## 运行前准备

需要准备的最小环境：

- Python 3.10+
- `uv`
- Hugo Extended
- 一个能访问目标数据库的 Notion Integration

启用 AI 翻译和摘要时，还需要：

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

## 安装方式

如果你在自己的 Hugo 站点中以子目录方式使用本项目，推荐在 Hugo 站点根目录执行：

```bash
git submodule add https://github.com/binbinsh/notion-autoblog notion-autoblog
git submodule update --init --recursive
uv venv --python 3.10
uv pip install notion-autoblog/
```

如果你直接在本仓库里维护示例站点，则在仓库根目录执行：

```bash
uv venv --python 3.10
uv pip install .
```

## 核心环境变量

必须提供：

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

可选项：

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_TRANSLATION_MODEL`
- `CLOUDFLARE_SUMMARY_MODEL`
- `HUGO_SITE_DIR`
- `HUGO_CONTENT_DIR`
- `HUGO_STATIC_DIR`
- `NOTION_CACHE_FILE`

默认情况下，缓存文件位于目标站点根目录下的 `.notion_cache.json`。

## 基本运行方式

在 Hugo 站点根目录运行：

```bash
uv run notion-autoblog --site-dir .
```

从其他目录运行：

```bash
uv run notion-autoblog --site-dir /absolute/path/to/site
```

如果需要清理现有生成内容后再同步：

```bash
uv run notion-autoblog --site-dir /absolute/path/to/site --clean
```

## 生成结果

同步完成后会生成以下内容：

- Markdown 页面写入 `content/`
- 图片写入 `static/images/`
- 视频写入 `static/videos/`
- 音频写入 `static/audios/`
- 附件与 PDF 写入 `static/files/`
- 同步状态、媒体映射、翻译结果、摘要结果写入 `.notion_cache.json`

slug 会被当作 Hugo 路径使用，例如：

- `post-title` -> `content/post-title.md`
- `posts/post-title` -> `content/posts/post-title.md`

如果启用了 `params.notion.contentSection = "posts"`，裸 slug 也会被归档到 `content/posts/`。

## 多语言行为

语言集合来自 Hugo 配置，而不是 Notion 元数据。当前实现逻辑是：

1. 读取站点 Hugo 配置。
2. 解析 `languages` 和默认语言。
3. 将第一语言视为默认输出语言。
4. 若配置了 AI，向其余语言生成翻译页面。

生成后的翻译页会写入这些 front matter 字段：

- `notion_source_language`
- `notion_translation_language`
- `notion_source_path`
- `translationKey`

## 摘要行为

如果配置了 Cloudflare Workers AI：

- 源语言页面会生成摘要
- 翻译页面会生成目标语言摘要
- 摘要写入 front matter 的 `summary`

如果 AI 不可用，系统会回退到本地提取的首段摘要。

## 缓存机制

当前缓存分为三类：

- 媒体缓存
- 翻译缓存
- 摘要缓存

翻译缓存键由这些输入构成：

- 模型名
- 源语言
- 目标语言
- 字段类型（`title` 或 `content`）
- 原始文本内容

摘要缓存键由这些输入构成：

- 模型名
- 语言
- 标题
- 内容

这意味着只要标题、正文、目标语言或模型发生变化，就会重新调用 AI。

## 示例站点

`examples/trainsh-blog/` 是当前仓库维护的参考站点，包含：

- Hugo 配置
- 站点级 layout 覆盖
- Cloudflare Worker 配置
- `hugo-trainsh` 子模块主题

根目录 workflow 会直接同步和部署这个示例站点。
