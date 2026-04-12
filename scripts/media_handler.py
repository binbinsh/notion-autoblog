import os
import requests
import hashlib
import re
from urllib.parse import urlparse, unquote
from typing import Optional
from PIL import Image
import logging

logger = logging.getLogger(__name__)

class MediaHandler:
    def __init__(self, static_dir: str = "static", cache_manager=None):
        # Keep site-relative for returned paths, but download using absolute
        self.static_dir_rel = static_dir
        self.static_dir_abs = os.path.abspath(static_dir)
        self.cache_manager = cache_manager
        self.image_dir = os.path.join(self.static_dir_abs, "images")
        self.video_dir = os.path.join(self.static_dir_abs, "videos")
        self.audio_dir = os.path.join(self.static_dir_abs, "audios")

        # Create directories
        for dir_path in [self.image_dir, self.video_dir, self.audio_dir]:
            os.makedirs(dir_path, exist_ok=True)

    def download_media(self, url: str, media_type: str = "image", last_edited_time: Optional[str] = None) -> Optional[str]:
        """Download media file and return local path"""
        try:
            if self.cache_manager:
                cached_path = self.cache_manager.get_cached_media(url, last_edited_time)
                if cached_path:
                    # cached_path is stored as site-relative (e.g., "/images/<file>")
                    abs_cached = os.path.join(self.static_dir_abs, cached_path.lstrip('/'))
                    if os.path.exists(abs_cached):
                        logger.info(f"Media cache HIT for {media_type}: {url[:50]}... -> {cached_path}")
                        return cached_path
                    else:
                        logger.info(f"Media cache MISS (file missing): {cached_path}; re-downloading")

            # Generate stable filename (prefers Notion file UUID when available)
            filename = self._generate_filename(url)

            # Determine save directory
            if media_type == "image":
                save_dir = self.image_dir
                relative_path = f"/images/{filename}"
            elif media_type == "video":
                save_dir = self.video_dir
                relative_path = f"/videos/{filename}"
            elif media_type == "audio":
                save_dir = self.audio_dir
                relative_path = f"/audios/{filename}"
            else:
                return url

            file_path = os.path.join(save_dir, filename)

            # If file exists, backfill cache and return
            if os.path.exists(file_path):
                if self.cache_manager:
                    self.cache_manager.cache_media(url, relative_path, last_edited_time)
                logger.info(f"Media found on disk (backfilling cache): {media_type} {filename}")
                return relative_path

            # Download file
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # Optimize image if applicable
            if media_type == "image":
                self._optimize_image(file_path)

            logger.info(f"Media cache MISS (downloading): {media_type} {filename} from {url[:50]}...")

            # Update cache after successful download
            if self.cache_manager and relative_path:
                self.cache_manager.cache_media(url, relative_path, last_edited_time)
                logger.debug(f"Cached mapping: {url} -> {relative_path}")

            return relative_path

        except Exception as e:
            logger.error(f"Error downloading media from {url}: {e}")
            return url  # Return original URL on failure

    def _generate_filename(self, url: str) -> str:
        """Generate a stable filename for the URL.

        - For Notion-hosted files, use the file UUID as the basename.
        - For external files, use md5(url) prefix and preserve extension when possible.
        """
        # Extract parts
        parsed = urlparse(url)
        original_name = os.path.basename(unquote(parsed.path))
        _, ext = os.path.splitext(original_name)

        # New S3-style URLs
        s3_match = re.search(r"s3\..*\.amazonaws\.com/([0-9a-fA-F\-]{36})/([0-9a-fA-F\-]{36})/", url)
        if s3_match:
            file_uuid = s3_match.group(2).lower()
            return f"{file_uuid}{ext}"

        # Legacy notion-static URLs
        m = re.search(r"secure\.notion-static\.com/([0-9a-fA-F\-]{36})/", url)
        if m:
            file_uuid = m.group(1).lower()
            if not ext:
                ext = ".jpg"
            return f"{file_uuid}{ext}"

        # External: md5(url) with best-guess extension
        hash_name = hashlib.md5(url.encode()).hexdigest()[:8]
        if not ext:
            ext = ".jpg"
        return f"{hash_name}{ext}"

    def _optimize_image(self, file_path: str, max_width: int = 1920):
        """Optimize image size and quality"""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            with Image.open(file_path) as img:
                # If animated (e.g., GIF/WebP animations), do not modify to preserve animation
                if getattr(img, "is_animated", False) or ext == ".gif":
                    return

                # Resize if wider than max_width
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                # Save using original format settings
                if ext in (".jpg", ".jpeg"):
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.save(file_path, "JPEG", quality=85, optimize=True, progressive=True)
                elif ext == ".png":
                    # Keep transparency and PNG format
                    img.save(file_path, "PNG", optimize=True)
                elif ext == ".webp":
                    img.save(file_path, "WEBP", quality=85, method=6)
                else:
                    # For other formats, skip to avoid unexpected conversions
                    return
        except Exception as e:
            logger.warning(f"Failed to optimize image {file_path}: {e}")
