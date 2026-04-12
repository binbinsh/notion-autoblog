# translation 模块用法

## 作用

`translation` 模块用于在翻译页面顶部渲染机器翻译提示，适合由 `notion-autoblog` 生成的多语言内容。

## 引入方式

```toml
[module]
  replacements = "github.com/binbinsh/notion-autoblog/modules/translation -> ../notion-autoblog/modules/translation"

  [[module.imports]]
    path = "github.com/binbinsh/notion-autoblog/modules/translation"
```

如果你的本地目录名不是 `notion-autoblog`，请同步修改 replacement 路径。

## partial 接入

推荐在文章模板中直接调用：

```go-html-template
{{ partial "translation/notice.html" . }}
```

当页面 front matter 包含以下字段时，模块会自动渲染提示：

- `notion_source_language`
- `notion_translation_language`
- `notion_source_path`

## shortcode 接入

如果你希望手动控制提示位置，也可以在 Markdown 中使用 shortcode：

```md
{{< translation-note sourceLang="zh" sourcePath="posts/example.zh.md" >}}
```

未显式传参时，shortcode 会回退到当前页面 front matter。
