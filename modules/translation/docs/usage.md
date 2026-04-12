# translation 模块

## 作用
为 `notion-autoblog` 生成的译文页面提供统一的“机器翻译提示”组件。

模块提供两种接入方式：

- partial：适合主题统一接入
- shortcode：适合在内容中手动插入

## 导入方式
站点需先初始化 Hugo Modules，并在配置中导入本模块。

示例：

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/translation -> ../notion-autoblog/modules/translation"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/translation"
```

若你的站点不是以 `notion-autoblog/` 作为本地目录名，请按实际路径修改 `replacements`。

## partial 接入
在文章模板中、正文上方插入：

```go-html-template
{{ partial "notion-translation/notice.html" . }}
```

当页面 front matter 同时包含以下字段时，组件会自动显示：

- `notion_source_language`
- `notion_source_path`

## shortcode 接入
也可以在 Markdown 中手动插入：

```md
{{< notion-translation-note sourceLang="zh" sourcePath="blog/example.zh.md" >}}
```

若省略参数，shortcode 会回退到当前页面的 front matter。
