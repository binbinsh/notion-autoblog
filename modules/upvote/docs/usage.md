# upvote 模块用法

## 作用

`upvote` 模块提供一个 Hugo 点赞组件，以及配套的 Cloudflare Worker 后端示例。

## 引入方式

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

## 站点配置

```toml
[params.upvote]
  enabled = true
  endpoint = "/api/upvote"
  infoEndpoint = "/api/upvote-info"
```

## partial 接入

推荐在文章页底部或元信息区域渲染：

```go-html-template
{{ partial "upvote/widget.html" . }}
```

## shortcode 接入

如果需要在 Markdown 中手动插入：

```md
{{< upvote >}}
```

## 后端文件

Cloudflare Worker 示例位于：

- `cloudflare/worker.py`
- `cloudflare/wrangler.toml`

部署前需要准备：

- 一个 KV namespace
- `UPVOTE_COOKIE_SECRET`
