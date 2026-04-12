import unittest

from notion_service import NotionClient


class NotionClientBlockTests(unittest.TestCase):
    def test_get_page_blocks_recurses_and_paginates(self):
        client = NotionClient("token", "database-id")

        responses = {
            ("/blocks/page-id/children", None): {
                "results": [
                    {
                        "id": "block-1",
                        "type": "paragraph",
                        "has_children": True,
                    }
                ],
                "has_more": True,
                "next_cursor": "cursor-1",
            },
            ("/blocks/page-id/children", "cursor-1"): {
                "results": [
                    {
                        "id": "block-2",
                        "type": "paragraph",
                        "has_children": False,
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            },
            ("/blocks/block-1/children", None): {
                "results": [
                    {
                        "id": "child-1",
                        "type": "paragraph",
                        "has_children": False,
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            },
        }

        def fake_request(method, path, *, params=None, json_body=None, timeout=30):
            self.assertEqual(method, "GET")
            self.assertIsNone(json_body)
            self.assertEqual(timeout, 60)
            start_cursor = (params or {}).get("start_cursor")
            return responses[(path, start_cursor)]

        client._request = fake_request

        blocks = client._get_page_blocks("page-id")

        self.assertEqual([block["id"] for block in blocks], ["block-1", "block-2"])
        self.assertEqual([child["id"] for child in blocks[0]["children"]], ["child-1"])


if __name__ == "__main__":
    unittest.main()
