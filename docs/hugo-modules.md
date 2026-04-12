# Hugo 模块

## 当前模块
仓库当前提供两个可复用的 Hugo Modules：

- `modules/translation`
- `modules/upvote`

## 使用前提
站点需先初始化 Hugo Modules：

```bash
hugo mod init example.com/your-site
```

## 本地 submodule 场景
若站点目录结构如下：

```text
your-site/
├── themes/
└── notion-autoblog/
```

则可在 Hugo 配置中写入：

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/translation -> ../notion-autoblog/modules/translation,github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/translation"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

注意：
- `replacements` 的相对路径是相对于 `themesDir`
- 默认 `themesDir` 为站点根目录下的 `themes/`

## 主题为 git submodule 时的建议
若 `themes/hugo-trainsh/` 或其他主题目录本身也是 git submodule，建议保持主题仓库干净，不直接把模块接入逻辑写进主题。

更稳妥的做法是：
- 主题继续只负责主题本身
- 站点在 `layouts/` 下覆盖对应模板
- 覆盖层中再调用 `translation` 或 `upvote` 模块 partial

例如：

```go-html-template
{{ partial "notion-translation/notice.html" . }}
{{ partial "notion-upvote/widget.html" . }}
```

## translation 模块
用途：
- 为自动翻译页面渲染统一提示

推荐接入：

```go-html-template
{{ partial "notion-translation/notice.html" . }}
```

模块文档：
- `modules/translation/docs/usage.md`

## upvote 模块
用途：
- 为文章页渲染点赞组件
- 提供 Cloudflare Worker 后端示例

推荐接入：

```go-html-template
{{ partial "notion-upvote/widget.html" . }}
```

模块文档：
- `modules/upvote/docs/usage.md`
