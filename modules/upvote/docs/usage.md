# upvote 模块

## 作用
为 Hugo 站点提供可复用的点赞组件，以及配套的 Cloudflare Worker 后端示例。

模块提供两种接入方式：

- partial：适合主题统一接入
- shortcode：适合在内容中手动插入

## 导入方式
示例：

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/upvote -> ../notion-autoblog/modules/upvote"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/upvote"
```

## 站点配置
在 Hugo 配置中启用：

```toml
[params]
  [params.upvote]
    enabled = true
    endpoint = "/api/upvote"
    infoEndpoint = "/api/upvote-info"
```

## partial 接入
在主题模板中插入：

```go-html-template
{{ partial "notion-upvote/widget.html" . }}
```

## shortcode 接入
在 Markdown 内容中插入：

```md
{{< notion-upvote >}}
```

## Cloudflare Worker
后端示例位于：

- `cloudflare/worker.py`
- `cloudflare/wrangler.toml`

部署前请先创建 KV，并设置 `UPVOTE_COOKIE_SECRET`。
