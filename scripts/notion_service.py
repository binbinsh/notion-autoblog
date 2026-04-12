from datetime import datetime
from typing import List, Dict, Any, Optional
from notion_client import Client
from retry_decorator import retry
import logging
import requests

logger = logging.getLogger(__name__)

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
        self.blocks: List[Dict[str, Any]] = []


class NotionClient:
    def __init__(self, token: str, database_id: str):
        self.client = Client(auth=token, notion_version="2025-09-03")
        self.database_id = database_id
        self._token = token
        self._api_base = "https://api.notion.com/v1"
        # Use latest header for endpoints requiring 2025-09-03 (data sources)
        self._latest_headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json",
        }
        # Cache for discovered data source id
        self._data_source_id: Optional[str] = None

    def _fetch_database_latest(self) -> Dict[str, Any]:
        """Retrieve the database using the latest API version to access data_sources."""
        url = f"{self._api_base}/databases/{self.database_id}"
        resp = requests.get(url, headers=self._latest_headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _ensure_data_source_id(self) -> str:
        """Resolve and cache the data_source_id for the configured database.

        If the database has multiple data sources, the first is used by default.
        """
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

    def _query_data_source(self, *, filter: Optional[Dict[str, Any]] = None, page_size: Optional[int] = None, start_cursor: Optional[str] = None) -> Dict[str, Any]:
        """Query pages from the resolved data source using the new endpoint.

        POST /v1/data_sources/{data_source_id}/query
        """
        data_source_id = self._ensure_data_source_id()
        url = f"{self._api_base}/data_sources/{data_source_id}/query"
        body: Dict[str, Any] = {}
        if filter is not None:
            body["filter"] = filter
        if page_size is not None:
            body["page_size"] = page_size
        if start_cursor is not None:
            body["start_cursor"] = start_cursor

        resp = requests.post(url, json=body, headers=self._latest_headers, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _fetch_data_source(self, data_source_id: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve the data source object using the latest API version.

        This is required because the database properties are now exposed
        at the data source layer in the latest Notion API.
        """
        ds_id = data_source_id or self._ensure_data_source_id()
        url = f"{self._api_base}/data_sources/{ds_id}"
        resp = requests.get(url, headers=self._latest_headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_database_properties(self) -> Dict[str, Any]:
        """Return database properties exclusively from the data source."""
        data_source = self._fetch_data_source()
        return data_source.get("properties", {})

    def test_connection(self) -> Dict[str, Any]:
        """Test connection to Notion database"""
        result = {
            "success": False,
            "database_info": None,
            "error": None,
            "warnings": []
        }

        try:
            # 1. Test if Token is valid
            logger.info("Testing Notion API token...")
            user_info = self.client.users.me()
            logger.info(f"✅ Token is valid. Bot ID: {user_info['id']}")

            # 2. Test database access (latest version to access data_sources)
            logger.info(f"Testing database access: {self.database_id}")
            database = self._fetch_database_latest()

            # 3. Extract database information
            db_title = "Untitled"
            if database.get('title') and len(database['title']) > 0:
                db_title = database['title'][0]['plain_text']

            logger.info(f"✅ Successfully connected to database: {db_title}")

            # 4. Check required properties (use data source schema first)
            properties = self.get_database_properties()
            logger.info(f"Database properties: {properties}")
            required_props = {
                'Title': 'title',
                'Published': 'checkbox',
                'Date': 'date',
                'Slug': 'rich_text',
                'Tags': 'multi_select'
            }

            missing_props = []
            wrong_type_props = []

            for prop_name, expected_type in required_props.items():
                if prop_name not in properties:
                    missing_props.append(prop_name)
                elif properties[prop_name].get('type') != expected_type:
                    actual_type = properties[prop_name].get('type', 'unknown')
                    wrong_type_props.append(
                        f"{prop_name} (expected {expected_type}, got {actual_type})"
                    )

            # 5. Generate warning messages
            if missing_props:
                warning = f"Missing properties: {', '.join(missing_props)}"
                result['warnings'].append(warning)
                logger.warning(f"⚠️  {warning}")

            if wrong_type_props:
                warning = f"Wrong property types: {', '.join(wrong_type_props)}"
                result['warnings'].append(warning)
                logger.warning(f"⚠️  {warning}")

            # 6. Test query permissions via data source
            logger.info("Testing query permissions...")
            test_query = self._query_data_source(page_size=1)

            total_posts = len(test_query.get('results', []))
            has_more = test_query.get('has_more', False)

            logger.info(f"✅ Query successful. Found at least {total_posts} post(s)")

            # 7. Summarize results
            result['success'] = True
            result['database_info'] = {
                'id': self.database_id,
                'title': db_title,
                'properties': list(properties.keys()),
                'total_properties': len(properties),
                'sample_post_count': total_posts,
                'has_more_posts': has_more
            }

            # 8. Display database properties
            logger.info("📋 Database Properties:")
            for prop_name, prop_info in properties.items():
                prop_type = prop_info.get('type', 'unknown')
                logger.info(f"   - {prop_name}: {prop_type}")

            return result

        except Exception as e:
            error_msg = str(e)
            result['error'] = error_msg

            # Provide more friendly error messages
            if "unauthorized" in error_msg.lower():
                logger.error("❌ Authorization failed!")
                logger.error("   Please check:")
                logger.error("   1. Your NOTION_TOKEN is correct")
                logger.error("   2. The Integration has access to the database")
                logger.error("   3. The database is shared with your Integration")
            elif "not found" in error_msg.lower():
                logger.error("❌ Database not found!")
                logger.error("   Please check:")
                logger.error("   1. Your NOTION_DATABASE_ID is correct")
                logger.error("   2. The ID format (with or without hyphens)")
            elif "rate_limited" in error_msg.lower():
                logger.error("❌ Rate limited by Notion API!")
                logger.error("   Please wait a moment and try again")
            else:
                logger.error(f"❌ Connection failed: {error_msg}")

            return result

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            # Query published posts
            published_response = self._query_data_source(
                filter={
                    "property": "Published",
                    "checkbox": {"equals": True}
                }
            )

            # Query all posts
            all_response = self._query_data_source(page_size=1)

            published_count = len(published_response.get('results', []))

            # If there are more pages, show "at least" count
            published_more = published_response.get('has_more', False)
            all_more = all_response.get('has_more', False)

            stats = {
                'published_posts': f"{published_count}{'+ ' if published_more else ''}",
                'total_posts': f"{'at least ' if all_more else ''}1+",
                'database_id': self.database_id
            }

            return stats

        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            return {}

    @retry(max_attempts=3, delay=2, exceptions=(requests.RequestException,))
    def get_published_posts(self) -> List[NotionPost]:
        """Get all published posts (paginated)."""
        try:
            posts: List[NotionPost] = []
            start_cursor: Optional[str] = None

            while True:
                response = self._query_data_source(
                    filter={
                        "property": "Published",
                        "checkbox": {"equals": True}
                    },
                    page_size=100,
                    start_cursor=start_cursor
                )

                for page in response.get('results', []):
                    post = self._parse_page(page)
                    if post:
                        posts.append(post)

                if response.get('has_more'):
                    start_cursor = response.get('next_cursor')
                else:
                    break

            return posts
        except Exception as e:
            logger.error(f"Error fetching posts: {e}")
            return []

    def _parse_page(self, page: Dict[str, Any]) -> Optional[NotionPost]:
        """Parse page data"""
        try:
            post = NotionPost()
            post.id = page['id']

            props = page['properties']

            # Title
            if 'Title' in props and props['Title']['title']:
                post.title = props['Title']['title'][0]['plain_text']
            else:
                post.title = "Untitled"

            # Slug
            if 'Slug' in props and props['Slug']['rich_text']:
                post.slug = props['Slug']['rich_text'][0]['plain_text']
            else:
                post.slug = page['id'].replace('-', '')

            # Date
            if 'Date' in props and props['Date']['date']:
                post.date = datetime.fromisoformat(
                    props['Date']['date']['start'].replace('Z', '+00:00')
                )

            # Tags
            if 'Tags' in props and props['Tags']['multi_select']:
                post.tags = [tag['name'] for tag in props['Tags']['multi_select']]

            # Category/Categories (optional)
            category_prop = props.get('Category') or props.get('Categories')
            if category_prop:
                if category_prop.get('select'):
                    selected = category_prop['select']
                    if selected and selected.get('name'):
                        post.categories = [selected['name']]
                elif category_prop.get('multi_select'):
                    post.categories = [c['name'] for c in category_prop['multi_select']]
                elif category_prop.get('type') not in (None, 'select', 'multi_select'):
                    logger.warning(
                        "Unsupported 'Category/Categories' property type: %s",
                        category_prop.get('type', 'unknown'),
                    )

            # Cover image
            if page.get('cover'):
                cover = page['cover']
                if cover['type'] == 'external':
                    post.cover_image = cover['external']['url']
                elif cover['type'] == 'file':
                    post.cover_image = cover['file']['url']

            # Last edited time
            post.last_edited = datetime.fromisoformat(
                page['last_edited_time'].replace('Z', '+00:00')
            )

            # Get all page blocks
            post.blocks = self._get_page_blocks(post.id)

            return post
        except Exception as e:
            logger.error(f"Error parsing page {page.get('id', 'unknown')}: {e}")
            return None

    def _get_page_blocks(self, page_id: str) -> List[Dict[str, Any]]:
        """Get all blocks of a page with full nested children (recursive)."""

        def fetch_children_recursively(block_id: str) -> List[Dict[str, Any]]:
            collected_blocks: List[Dict[str, Any]] = []
            local_has_more = True
            local_cursor = None

            while local_has_more:
                try:
                    if local_cursor:
                        resp = self.client.blocks.children.list(
                            block_id=block_id,
                            start_cursor=local_cursor
                        )
                    else:
                        resp = self.client.blocks.children.list(block_id=block_id)

                    items = resp.get('results', [])

                    for b in items:
                        # Recursively populate children for any block that has them
                        if b.get('has_children'):
                            try:
                                b['children'] = fetch_children_recursively(b['id'])
                            except Exception as child_err:
                                logger.warning(
                                    f"Failed to fetch children for block {b.get('id')}: {child_err}"
                                )
                                b['children'] = []

                        collected_blocks.append(b)

                    local_has_more = resp.get('has_more', False)
                    local_cursor = resp.get('next_cursor')
                except Exception as e:
                    logger.error(f"Error fetching children for block {block_id}: {e}")
                    break

            return collected_blocks

        # Top-level: page_id is also a block container for its direct children
        return fetch_children_recursively(page_id)
