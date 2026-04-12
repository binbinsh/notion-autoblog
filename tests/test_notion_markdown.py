import unittest

from notion_markdown import NotionMarkdownAdapter


class _FakeMediaHandler:
    def download_media(self, url: str, media_type: str):
        filename = url.rstrip("/").split("/")[-1] or f"{media_type}.bin"
        return f"/{media_type}s/{filename}"


class NotionMarkdownAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = NotionMarkdownAdapter(_FakeMediaHandler())
        page_id = "12345678-1234-1234-1234-123456789012"
        self.adapter.set_id_to_slug_mapping(
            {
                page_id: "blog/internal-target",
                page_id.replace("-", ""): "blog/internal-target",
            },
            {
                page_id: "Internal Target",
                page_id.replace("-", ""): "Internal Target",
            },
        )

    def test_converts_media_and_internal_links(self):
        markdown = """# Hello World

Intro paragraph with a [page link](https://www.notion.so/Internal-Target-12345678123412341234123456789012).

![Cover](https://cdn.example.com/cover.png)

<file src="https://cdn.example.com/report.pdf">Report</file>

<page url="https://www.notion.so/Internal-Target-12345678123412341234123456789012">Target</page>
"""
        converted = self.adapter.convert(markdown, page_title="Hello World")

        self.assertNotIn("# Hello World", converted)
        self.assertIn("![Cover](/images/cover.png)", converted)
        self.assertIn("📎 [Report](/files/report.pdf)", converted)
        self.assertIn('[page link]({{< relref path="blog/internal-target.md" >}})', converted)
        self.assertIn('[Target]({{< relref path="blog/internal-target.md" >}})', converted)

    def test_converts_callouts_and_toggle_blocks(self):
        markdown = """<callout icon="💡">
\tImportant line
\t- Child bullet
</callout>

## Expand me {toggle="true"}
\tHidden text
"""
        converted = self.adapter.convert(markdown)

        self.assertIn("> 💡 Important line", converted)
        self.assertIn("> - Child bullet", converted)
        self.assertIn("<details>", converted)
        self.assertIn("<summary>Expand me</summary>", converted)
        self.assertIn("Hidden text", converted)


if __name__ == "__main__":
    unittest.main()
