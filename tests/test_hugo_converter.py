import tempfile
import unittest
from pathlib import Path

from hugo_converter import HugoConverter


class _FakeMediaHandler:
    def download_media(self, url: str, media_type: str, last_edited_time=None):
        return f"/{media_type}s/{Path(url).name or 'file.bin'}"


class _FakeSummarizer:
    def summarize(self, language: str, title: str, content: str) -> str:
        return f"{language}:{title}"


class _Post:
    def __init__(self):
        self.id = "12345678-1234-1234-1234-123456789012"
        self.title = "Hello"
        self.slug = "blog/hello-world"
        self.date = __import__("datetime").datetime(2026, 4, 12, 12, 0, 0)
        self.last_edited = __import__("datetime").datetime(2026, 4, 12, 12, 30, 0)
        self.tags = ["tag"]
        self.categories = []
        self.blocks = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"plain_text": "Section"}],
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "First paragraph."}],
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Second paragraph."}],
                },
            },
        ]
        self.cover_image = None


class HugoConverterTests(unittest.TestCase):
    def test_normalize_slug_path_remaps_legacy_section(self):
        converter = HugoConverter("/tmp", _FakeMediaHandler())
        converter.set_content_config(content_section="posts", section_aliases=["blog"])

        self.assertEqual(converter.normalize_slug_path("blog/hello-world"), ["posts", "hello-world"])
        self.assertEqual(converter.normalize_slug_path("hello-world"), ["posts", "hello-world"])
        self.assertEqual(converter.normalize_slug_path("posts/hello-world"), ["posts", "hello-world"])

    def test_convert_post_writes_summary_and_posts_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            converter = HugoConverter(tmpdir, _FakeMediaHandler())
            converter.set_content_config(content_section="posts", section_aliases=["blog"])
            converter.set_summary_service(_FakeSummarizer())
            converter.set_translation_config(["en"], translator=None)

            post = _Post()
            self.assertTrue(converter.convert_post(post))

            output_file = Path(tmpdir) / "posts" / "hello-world.md"
            self.assertTrue(output_file.exists())
            content = output_file.read_text(encoding="utf-8")
            self.assertIn("summary: en:Hello", content)
            self.assertIn("translationKey: 12345678-1234-1234-1234-123456789012", content)
            self.assertIn("## Section {#11111111111111111111111111111111}", content)
            self.assertIn("First paragraph.", content)

    def test_fallback_summary_prefers_intro_paragraphs(self):
        converter = HugoConverter("/tmp", _FakeMediaHandler())
        content = (
            "# Title\n\n"
            "This opening paragraph sounds like the author's own introduction.\n"
            "It should stay together in the fallback summary.\n\n"
            "## Details\n\n"
            "This second paragraph should not be pulled in when the first paragraph is already long enough."
        )

        summary = converter._fallback_summary(content)

        self.assertEqual(
            summary,
            "This opening paragraph sounds like the author's own introduction. "
            "It should stay together in the fallback summary.",
        )

    def test_blocks_to_markdown_keeps_nested_lists(self):
        converter = HugoConverter("/tmp", _FakeMediaHandler())
        blocks = [
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "Parent"}]},
                "children": [
                    {
                        "type": "numbered_list_item",
                        "numbered_list_item": {"rich_text": [{"plain_text": "Child"}]},
                    }
                ],
            }
        ]

        content = converter._blocks_to_markdown(blocks)

        self.assertEqual(content, "- Parent\n    1. Child")


if __name__ == "__main__":
    unittest.main()
