#!/usr/bin/env python3
import os
import sys
import logging
import argparse
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

from notion_service import NotionClient
from hugo_converter import HugoConverter
from media_handler import MediaHandler
from logging_utils import setup_logging
from cache_manager import CacheManager
from translation_service import CloudflareAITranslator
from summary_service import CloudflareAISummarizer
from hugo_config import infer_languages_from_config, read_hugo_config

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)


def _resolve_site_path(site_dir: Path, raw_value: str | None, default_name: str) -> str:
    """Resolve a CLI path relative to the Hugo site root when needed."""
    candidate = (raw_value or "").strip()
    path = Path(candidate) if candidate else Path(default_name)
    if not path.is_absolute():
        path = site_dir / path
    return str(path.resolve())


def test_notion_connection(notion_client: NotionClient) -> bool:
    """Test Notion connection"""
    print("🔍 Testing Notion connection...")

    result = notion_client.test_connection()

    if result['success']:
        db_info = result['database_info']
        print(f"✅ Successfully connected to Notion!")
        print(f"📊 Database Information:")
        print(f"   - Name: {db_info['title']}")
        print(f"   - ID: {db_info['id'][:8]}...{db_info['id'][-8:]}")
        print(f"   - Properties: {db_info['total_properties']}")
        print(f"   - Sample Posts: {db_info['sample_post_count']}")

        if result['warnings']:
            print(f"⚠️  Warnings:")
            for warning in result['warnings']:
                print(f"   - {warning}")

        # Get statistics
        stats = notion_client.get_database_stats()
        if stats:
            print(f"📈 Database Statistics:")
            print(f"   - Published Posts: {stats.get('published_posts', 'Unknown')}")

        return True
    else:
        print(f"❌ Connection test failed!")
        if result['error']:
            print(f"   Error: {result['error']}")
        return False


def main():
    # Load environment variables
    load_dotenv()

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Sync Notion posts to Hugo')
    parser.add_argument('--site-dir', default=os.getenv('HUGO_SITE_DIR', '.'),
                        help='Hugo site root directory')
    parser.add_argument('--notion-token', default=os.getenv('NOTION_TOKEN'),
                        help='Notion API token')
    parser.add_argument('--database-id', default=os.getenv('NOTION_DATABASE_ID'),
                        help='Notion database ID')
    parser.add_argument('--content-dir', default=os.getenv('HUGO_CONTENT_DIR'),
                        help='Hugo content directory')
    parser.add_argument('--static-dir', default=os.getenv('HUGO_STATIC_DIR'),
                        help='Hugo static directory')
    parser.add_argument('--cache-file', default=os.getenv('NOTION_CACHE_FILE'),
                        help='Cache file path')
    parser.add_argument('--clean', action='store_true',
                        help='Clean existing posts before sync')
    parser.add_argument('--cloudflare-api-token', default=os.getenv('CLOUDFLARE_API_TOKEN'),
                        help='Cloudflare API token for Workers AI and deployment')
    parser.add_argument('--cloudflare-account-id', default=os.getenv('CLOUDFLARE_ACCOUNT_ID'),
                        help='Cloudflare account id for Workers AI')

    args = parser.parse_args()

    # Validate required parameters
    if not args.notion_token or not args.database_id:
        logger.error("NOTION_TOKEN and NOTION_DATABASE_ID are required")
        sys.exit(1)

    try:
        site_dir = Path(args.site_dir).expanduser().resolve()
        if not site_dir.exists():
            logger.error("Hugo site directory does not exist: %s", site_dir)
            sys.exit(1)

        content_dir = _resolve_site_path(site_dir, args.content_dir, "content")
        static_dir = _resolve_site_path(site_dir, args.static_dir, "static")
        cache_file = _resolve_site_path(site_dir, args.cache_file, ".notion_cache.json")

        # Initialize components
        notion_client = NotionClient(args.notion_token, args.database_id)
        cache_manager = CacheManager(cache_file)
        media_handler = MediaHandler(static_dir, cache_manager=cache_manager)
        hugo_converter = HugoConverter(content_dir, media_handler, cache_manager=cache_manager)

        hugo_config = read_hugo_config(str(site_dir))
        languages = infer_languages_from_config(hugo_config)
        params = hugo_config.get("params") or {}
        notion_params = params.get("notion") or {}
        content_section = (notion_params.get("contentsection") or notion_params.get("contentSection") or "").strip()
        section_aliases = notion_params.get("sectionaliases") or notion_params.get("sectionAliases") or []
        if not isinstance(section_aliases, list):
            section_aliases = []
        if languages:
            logger.info(
                "Inferred languages from Hugo: %s (default: %s)",
                ", ".join(languages),
                languages[0],
            )
        default_language = languages[0] if languages else None

        hugo_converter.set_content_config(
            content_section=content_section,
            section_aliases=section_aliases,
        )

        translator = None
        summarizer = None
        ai_available = bool(args.cloudflare_api_token and args.cloudflare_account_id)
        if languages:
            if not ai_available:
                logger.warning("CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID is not set; skipping AI translations")
            else:
                translator = CloudflareAITranslator(
                    args.cloudflare_api_token,
                    args.cloudflare_account_id,
                    cache_manager=cache_manager,
                )
                summarizer = CloudflareAISummarizer(
                    args.cloudflare_api_token,
                    args.cloudflare_account_id,
                    cache_manager=cache_manager,
                )
        else:
            logger.info("No Hugo language config found; skipping translations")
            if ai_available:
                summarizer = CloudflareAISummarizer(
                    args.cloudflare_api_token,
                    args.cloudflare_account_id,
                    cache_manager=cache_manager,
                )

        if languages:
            hugo_converter.set_translation_config(
                target_languages=languages,
                translator=translator,
            )
            logger.info("Configured target languages: %s (default: %s)", ", ".join(languages), default_language)
        hugo_converter.set_summary_service(summarizer)

        # Test connection
        if not test_notion_connection(notion_client):
            sys.exit(1)

        # Clean existing posts
        if args.clean:
            logger.info("Cleaning existing posts...")
            hugo_converter.clean_posts_directory()

        # Fetch Notion posts (includes blocks to regenerate Markdown each run)
        logger.info("Fetching posts from Notion...")
        posts = notion_client.get_published_posts()
        logger.info(f"Found {len(posts)} published posts")

        # Build ID -> slug map for internal link rewriting
        id_to_slug = {}
        id_to_title = {}
        for p in posts:
            post_id = getattr(p, 'id', None)
            post_slug = getattr(p, 'slug', None)
            post_title = getattr(p, 'title', None)

            if post_id and post_slug:
                # Store both hyphenated and compact IDs
                compact_id = post_id.replace('-', '')
                normalized_slug = hugo_converter.normalize_slug_path(post_slug)
                slug_path = "/".join(normalized_slug) if normalized_slug else post_slug
                id_to_slug[post_id] = slug_path
                id_to_slug[compact_id] = slug_path

            if post_id and post_title:
                compact_id = post_id.replace('-', '')
                id_to_title[post_id] = post_title
                id_to_title[compact_id] = post_title

        # Provide mapping to converter
        if hasattr(hugo_converter, 'set_id_to_slug_mapping'):
            hugo_converter.set_id_to_slug_mapping(id_to_slug, id_to_title)

        # Convert posts
        success_count = 0
        failed_posts = []
        with tqdm(total=len(posts), desc="Converting posts") as pbar:
            for post in posts:
                pbar.set_description(f"Converting: {post.title[:30]}...")
                if hugo_converter.convert_post(post):
                    success_count += 1
                    # Update per-post cache after successful conversion
                    cache_manager.update_post_cache(post.id, post.last_edited)
                else:
                    failed_posts.append(post.title)
                    logger.error("Failed to convert: %s", post.title)
                pbar.update(1)

        # Summarize results
        logger.info(f"Successfully converted {success_count}/{len(posts)} posts")
        if failed_posts:
            logger.error("Failed posts: %s", ", ".join(failed_posts))

        # Update last sync and persist cache
        cache_manager.update_last_sync()
        cache_manager.save_cache()

        if success_count < len(posts):
            sys.exit(1)

    except Exception as e:
        logger.error(f"Sync failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
