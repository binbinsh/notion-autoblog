from datetime import datetime
from typing import Any, Dict, List, Optional

import logging
import re

import requests

from retry_decorator import retry

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2026-03-11"


class NotionPost:
    def __init__(self):
        self.id: str = ""
        self.title: str = ""
        self.slug: str = ""
        self.date: datetime = datetime.now()
        self.tags: List[str] = []
        self.categories: List[str] = []
        self.content: str = ""
        self.last_edited: datetime = datetime.now()
        self.cover_image: Optional[str] = None


class NotionClient:
    def __init__(self, token: str, database_id: str):
        self.database_id = database_id
        self._api_base = "https://api.notion.com/v1"
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json",
            }
        )
        self._data_source_id: Optional[str] = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        url = f"{self._api_base}{path}"
        response = self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    def _fetch_database_latest(self) -> Dict[str, Any]:
        """Retrieve the database object using the latest API version."""
        return self._request("GET", f"/databases/{self.database_id}")

    def _ensure_data_source_id(self) -> str:
        """Resolve and cache the primary data source for the configured database."""
        if self._data_source_id:
            return self._data_source_id

        database_obj = self._fetch_database_latest()
        data_sources = database_obj.get("data_sources", []) or []
        if not data_sources:
            raise RuntimeError(
                "No data_sources found for the database. Please ensure the database has a data source."
            )

        if len(data_sources) > 1:
            logger.warning(
                "Multiple data sources detected for this database; using the first one: %s",
                data_sources[0].get("name") or data_sources[0].get("id"),
            )

        self._data_source_id = data_sources[0]["id"]
        return self._data_source_id

    def _query_data_source(
        self,
        *,
        filter: Optional[Dict[str, Any]] = None,
        page_size: Optional[int] = None,
        start_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query pages from the resolved data source using the latest endpoint."""
        body: Dict[str, Any] = {}
        if filter is not None:
            body["filter"] = filter
        if page_size is not None:
            body["page_size"] = page_size
        if start_cursor is not None:
            body["start_cursor"] = start_cursor

        data_source_id = self._ensure_data_source_id()
        return self._request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            json_body=body,
            timeout=60,
        )

    def _fetch_data_source(self, data_source_id: Optional[str] = None) -> Dict[str, Any]:
        ds_id = data_source_id or self._ensure_data_source_id()
        return self._request("GET", f"/data_sources/{ds_id}")

    def get_database_properties(self) -> Dict[str, Any]:
        """Return the database schema from the latest data source object."""
        data_source = self._fetch_data_source()
        return data_source.get("properties", {})

    def _fetch_current_user(self) -> Dict[str, Any]:
        return self._request("GET", "/users/me")

    def _fetch_page_markdown_once(
        self,
        page_id: str,
        *,
        include_transcript: bool = False,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if include_transcript:
            params["include_transcript"] = "true"
        return self._request(
            "GET",
            f"/pages/{page_id}/markdown",
            params=params,
            timeout=60,
        )

    def _fetch_page_markdown_recursive(
        self,
        page_id: str,
        *,
        include_transcript: bool = False,
        visited: Optional[set[str]] = None,
    ) -> str:
        visited = visited or set()
        normalized_page_id = page_id.replace("-", "").lower()
        if normalized_page_id in visited:
            return ""
        visited.add(normalized_page_id)

        payload = self._fetch_page_markdown_once(page_id, include_transcript=include_transcript)
        markdown = (payload.get("markdown") or "").replace("\r\n", "\n").replace("\r", "\n")
        unknown_block_ids = payload.get("unknown_block_ids", []) or []

        if payload.get("truncated"):
            logger.warning(
                "Notion markdown response truncated for %s; attempting to resolve %d unknown block(s)",
                page_id,
                len(unknown_block_ids),
            )

        for unknown_id in unknown_block_ids:
            subtree = self._fetch_unknown_subtree(
                unknown_id,
                include_transcript=include_transcript,
                visited=visited,
            )
            if not subtree:
                continue
            markdown = self._replace_unknown_placeholder(markdown, unknown_id, subtree)

        return markdown

    def _fetch_unknown_subtree(
        self,
        block_id: str,
        *,
        include_transcript: bool,
        visited: set[str],
    ) -> str:
        try:
            return self._fetch_page_markdown_recursive(
                block_id,
                include_transcript=include_transcript,
                visited=visited,
            )
        except requests.HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code == 404:
                logger.warning(
                    "Skipping inaccessible unknown block %s while resolving markdown subtree",
                    block_id,
                )
                return ""
            raise

    def _replace_unknown_placeholder(self, markdown: str, block_id: str, subtree: str) -> str:
        compact_id = block_id.replace("-", "").lower()
        patterns = [
            re.compile(
                rf'<unknown\b[^>]*url="[^"]*#{compact_id}[^"]*"[^>]*/>',
                re.IGNORECASE,
            ),
            re.compile(
                rf'<unknown\b[^>]*url="[^"]*{compact_id}[^"]*"[^>]*/>',
                re.IGNORECASE,
            ),
        ]

        replacement = subtree.strip()
        for pattern in patterns:
            new_markdown, count = pattern.subn(replacement, markdown, count=1)
            if count:
                return new_markdown

        logger.warning(
            "Failed to match unknown placeholder for %s; appending resolved subtree at the end",
            block_id,
        )
        if not markdown.strip():
            return replacement
        return f"{markdown.rstrip()}\n\n{replacement}"

    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Notion and the configured database."""
        result = {
            "success": False,
            "database_info": None,
            "error": None,
            "warnings": [],
        }

        try:
            logger.info("Testing Notion API token...")
            user_info = self._fetch_current_user()
            logger.info("Token is valid. Bot ID: %s", user_info.get("id"))

            logger.info("Testing database access: %s", self.database_id)
            database = self._fetch_database_latest()

            db_title = "Untitled"
            if database.get("title") and len(database["title"]) > 0:
                db_title = database["title"][0]["plain_text"]

            properties = self.get_database_properties()
            logger.info("Database properties: %s", properties)

            required_props = {
                "Title": "title",
                "Published": "checkbox",
                "Date": "date",
                "Slug": "rich_text",
                "Tags": "multi_select",
            }

            missing_props = []
            wrong_type_props = []

            for prop_name, expected_type in required_props.items():
                if prop_name not in properties:
                    missing_props.append(prop_name)
                elif properties[prop_name].get("type") != expected_type:
                    actual_type = properties[prop_name].get("type", "unknown")
                    wrong_type_props.append(
                        f"{prop_name} (expected {expected_type}, got {actual_type})"
                    )

            if missing_props:
                warning = f"Missing properties: {', '.join(missing_props)}"
                result["warnings"].append(warning)
                logger.warning(warning)

            if wrong_type_props:
                warning = f"Wrong property types: {', '.join(wrong_type_props)}"
                result["warnings"].append(warning)
                logger.warning(warning)

            logger.info("Testing query permissions...")
            test_query = self._query_data_source(page_size=1)
            sample_count = len(test_query.get("results", []))
            has_more = test_query.get("has_more", False)

            result["success"] = True
            result["database_info"] = {
                "id": self.database_id,
                "title": db_title,
                "properties": list(properties.keys()),
                "total_properties": len(properties),
                "sample_post_count": sample_count,
                "has_more_posts": has_more,
            }
            return result
        except Exception as exc:
            error_msg = str(exc)
            result["error"] = error_msg

            lowered = error_msg.lower()
            if "unauthorized" in lowered:
                logger.error("Authorization failed")
                logger.error("Please verify the token and database sharing permissions")
            elif "not found" in lowered:
                logger.error("Database not found")
                logger.error("Please verify NOTION_DATABASE_ID and database access")
            elif "rate_limited" in lowered:
                logger.error("Rate limited by Notion API")
            else:
                logger.error("Connection failed: %s", error_msg)
            return result

    def get_database_stats(self) -> Dict[str, Any]:
        """Return basic counts for the configured data source."""
        try:
            published_response = self._query_data_source(
                filter={
                    "property": "Published",
                    "checkbox": {"equals": True},
                }
            )
            all_response = self._query_data_source(page_size=1)

            published_count = len(published_response.get("results", []))
            published_more = published_response.get("has_more", False)
            all_more = all_response.get("has_more", False)

            return {
                "published_posts": f"{published_count}{'+ ' if published_more else ''}",
                "total_posts": f"{'at least ' if all_more else ''}1+",
                "database_id": self.database_id,
            }
        except Exception as exc:
            logger.error("Failed to get database stats: %s", exc)
            return {}

    @retry(max_attempts=3, delay=2, exceptions=(requests.RequestException,))
    def get_published_posts(self) -> List[NotionPost]:
        """Retrieve all published posts from the configured data source."""
        posts: List[NotionPost] = []
        start_cursor: Optional[str] = None

        while True:
            response = self._query_data_source(
                filter={
                    "property": "Published",
                    "checkbox": {"equals": True},
                },
                page_size=100,
                start_cursor=start_cursor,
            )

            for page in response.get("results", []):
                post = self._parse_page(page)
                if post:
                    posts.append(post)

            if not response.get("has_more"):
                break
            start_cursor = response.get("next_cursor")

        return posts

    def _parse_page(self, page: Dict[str, Any]) -> Optional[NotionPost]:
        """Parse a data source query result into a NotionPost."""
        try:
            post = NotionPost()
            post.id = page["id"]
            props = page["properties"]

            if "Title" in props and props["Title"]["title"]:
                post.title = props["Title"]["title"][0]["plain_text"]
            else:
                post.title = "Untitled"

            if "Slug" in props and props["Slug"]["rich_text"]:
                post.slug = props["Slug"]["rich_text"][0]["plain_text"]
            else:
                post.slug = post.id.replace("-", "")

            if "Date" in props and props["Date"]["date"]:
                post.date = datetime.fromisoformat(
                    props["Date"]["date"]["start"].replace("Z", "+00:00")
                )

            if "Tags" in props and props["Tags"]["multi_select"]:
                post.tags = [tag["name"] for tag in props["Tags"]["multi_select"]]

            category_prop = props.get("Category") or props.get("Categories")
            if category_prop:
                if category_prop.get("select"):
                    selected = category_prop["select"]
                    if selected and selected.get("name"):
                        post.categories = [selected["name"]]
                elif category_prop.get("multi_select"):
                    post.categories = [c["name"] for c in category_prop["multi_select"]]
                elif category_prop.get("type") not in (None, "select", "multi_select"):
                    logger.warning(
                        "Unsupported 'Category/Categories' property type: %s",
                        category_prop.get("type", "unknown"),
                    )

            if page.get("cover"):
                cover = page["cover"]
                if cover["type"] == "external":
                    post.cover_image = cover["external"]["url"]
                elif cover["type"] == "file":
                    post.cover_image = cover["file"]["url"]

            post.last_edited = datetime.fromisoformat(
                page["last_edited_time"].replace("Z", "+00:00")
            )
            post.content = self._fetch_page_markdown_recursive(post.id)
            return post
        except Exception as exc:
            logger.error("Error parsing page %s: %s", page.get("id", "unknown"), exc)
            return None
