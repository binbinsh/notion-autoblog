import tempfile
import unittest
from pathlib import Path

from cache_manager import CacheManager


class CacheManagerTests(unittest.TestCase):
    def test_translation_and_summary_cache_survive_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / ".notion_cache.json"
            cache = CacheManager(str(cache_file))
            cache.cache_translation("translation-key", {"text": "Hello", "field": "content"})
            cache.cache_summary("summary-key", {"text": "Summary"})
            cache.save_cache()

            reloaded_cache = CacheManager(str(cache_file))

            self.assertEqual(
                reloaded_cache.get_cached_translation("translation-key"),
                {"text": "Hello", "field": "content"},
            )
            self.assertEqual(
                reloaded_cache.get_cached_summary("summary-key"),
                {"text": "Summary"},
            )


if __name__ == "__main__":
    unittest.main()
