# 快速开始

## 适用场景
适用于已经有 Hugo 站点，准备把 Notion 数据库内容同步到 `content/` 并把媒体资源下载到 `static/` 的场景。

## 前置要求
- Python 3.10+
- Hugo Extended
- 可访问目标数据库的 Notion Integration

## 安装方式
在 Hugo 站点根目录执行：

```bash
git submodule add https://github.com/binbinsh/notion-autoblog notion-autoblog
git submodule update --init --recursive
uv venv --python 3.10
uv pip install notion-autoblog/
```

如需示例主题，可额外添加：

```bash
git submodule add https://github.com/binbinsh/hugo-trainsh.git themes/hugo-trainsh
```

## 必要环境变量
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

可选：
- `OPENROUTER_API_KEY`：启用自动翻译
- `HUGO_SITE_DIR`：默认 Hugo 站点根目录
- `HUGO_CONTENT_DIR`：覆盖内容输出目录
- `HUGO_STATIC_DIR`：覆盖静态资源目录
- `NOTION_CACHE_FILE`：覆盖缓存文件位置

## 运行同步
在 Hugo 站点根目录执行：

```bash
uv run notion-autoblog --site-dir .
```

若从其他目录触发同步，可显式指定站点目录：

```bash
uv run notion-autoblog --site-dir /absolute/path/to/site
```

## 输出规则
- slug 会被当作 Hugo 路径处理
- `blog/post-title` 会生成到 `content/blog/post-title.md`
- 图片、视频、音频会分别下载到 `static/images/`、`static/videos/`、`static/audios/`
- 缓存默认写入站点根目录的 `.notion_cache.json`

## 部署模板
仓库内提供 GitHub Actions 模板：

```bash
mkdir -p .github/workflows
cp notion-autoblog/templates/workflows/deploy-cloudflare.yml .github/workflows/
```

模板默认假设：
- 站点仓库根目录就是 Hugo 根目录
- `notion-autoblog/` 以 submodule 形式挂载在站点根目录
