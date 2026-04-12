import unittest

from summary_service import AISummarizer


class AISummarizerTests(unittest.TestCase):
    def test_build_system_prompt_asks_for_blog_blurb_voice(self):
        summarizer = AISummarizer("token", "account")

        prompt = summarizer._build_system_prompt("zh")

        self.assertIn("Write the summary in Chinese.", prompt)
        self.assertIn("blog blurb or opening note", prompt)
        self.assertIn("Avoid stock openings such as 'This post'", prompt)


if __name__ == "__main__":
    unittest.main()
