# notion-autoblog

从 Notion 最新 API 同步内容到 Hugo，使用官方 Enhanced Markdown，并提供翻译与 upvote 的 Hugo 模块。

```bash
git submodule add https://github.com/binbinsh/notion-autoblog notion-autoblog
uv venv --python 3.10
uv pip install notion-autoblog/
uv run notion-autoblog --site-dir .
```

- [快速开始](docs/quickstart.md)
- [多语言说明](docs/multilingual.md)
- [Hugo 模块](docs/hugo-modules.md)
- [仓库结构与 example](docs/repository-layout.md)
