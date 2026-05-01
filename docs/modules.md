# Hugo 模块

## 模块概览

当前仓库提供两个 Hugo 模块：

- `modules/translation`
- `modules/upvote`

它们都面向示例站点和下游 Hugo 站点复用。

需要特别说明：

- `summary` 不是独立 Hugo 模块
- 摘要能力属于同步管线内置功能
- 同步时生成的摘要会直接写入页面 front matter 的 `summary`

## 引入方式

在 Hugo 站点中初始化 Hugo Modules：

```bash
hugo mod init example.com/your-site
```

然后在 Hugo 配置中引入本仓库模块：

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/translation -> ../notion-autoblog/modules/translation,github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/translation"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

如果本地目录名不是 `notion-autoblog`，需要同步修改 replacement 路径。

## translation 模块

用途：

- 为翻译页面渲染机器翻译提示

推荐集成方式：

```go-html-template
{{ partial "translation/notice.html" . }}
```

也可以在 Markdown 中手动插入：

```md
{{< translation-note sourceLang="zh" sourcePath="posts/example.zh.md" >}}
```

模块会优先读取页面 front matter 中的这些字段：

- `notion_source_language`
- `notion_translation_language`
- `notion_source_path`

当页面不是翻译页时，不会输出提示。

## upvote 模块

用途：

- 为文章页面渲染点赞组件
- 提供对应的 Cloudflare Worker 后端示例

站点配置示例：

```toml
[params.upvote]
  enabled = true
  endpoint = "/api/upvote"
  infoEndpoint = "/api/upvote-info"
```

推荐集成方式：

```go-html-template
{{ partial "upvote/widget.html" . }}
```

也可以在 Markdown 中插入：

```md
{{< upvote >}}
```

## 示例站点中的接入方式

当前示例站点已经在 `examples/gridplanet/config.toml` 中导入这两个模块，并在站点级 layout 覆盖中完成接线：

- `translation` 用于文章正文前的翻译提示
- `upvote` 用于文章底部点赞区

这也是当前仓库推荐的集成方式：模块保持通用，站点层负责实际布局组合。

## Worker 后端位置

点赞后端示例位于：

- `modules/upvote/cloudflare/worker.py`
- `modules/upvote/cloudflare/wrangler.toml`

根目录 GitHub Actions workflow 会在示例站点部署时复用这套 Worker 逻辑。
