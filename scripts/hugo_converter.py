import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging
import yaml

from notion_markdown import NotionMarkdownAdapter

logger = logging.getLogger(__name__)


class HugoConverter:
    def __init__(self, content_dir: str, media_handler, cache_manager=None):
        self.content_dir = content_dir
        self.media_handler = media_handler
        self.cache_manager = cache_manager
        self.markdown_adapter = NotionMarkdownAdapter(media_handler)
        self.id_to_slug: Dict[str, str] = {}
        self.id_to_title: Dict[str, str] = {}
        self.translation_languages: List[str] = []
        self.translation_default_language: Optional[str] = None
        self.translation_service = None
        self.summary_service = None
        self.content_section: Optional[str] = None
        self.section_aliases: List[str] = []
        os.makedirs(self.content_dir, exist_ok=True)

    def set_translation_config(self, target_languages: List[str], translator=None):
        self.translation_languages = target_languages or []
        self.translation_default_language = (
            self.translation_languages[0] if self.translation_languages else None
        )
        self.translation_service = translator

    def set_summary_service(self, summarizer=None):
        self.summary_service = summarizer

    def set_content_config(self, *, content_section: Optional[str], section_aliases: Optional[List[str]] = None):
        self.content_section = (content_section or "").strip().strip("/") or None
        self.section_aliases = [alias.strip().strip("/") for alias in (section_aliases or []) if alias.strip()]

    def set_id_to_slug_mapping(
        self,
        mapping: Dict[str, str],
        title_mapping: Optional[Dict[str, str]] = None,
    ):
        self.id_to_slug = mapping or {}
        self.id_to_title = title_mapping or {}
        self.markdown_adapter.set_id_to_slug_mapping(self.id_to_slug, self.id_to_title)

    def normalize_slug_path(self, slug: str) -> List[str]:
        if not slug:
            return []
        cleaned = slug.strip().lstrip("/").strip("/")
        parts = [part for part in cleaned.split("/") if part]
        if not self.content_section:
            return parts
        if not parts:
            return [self.content_section]
        if parts[0] == self.content_section:
            return parts
        if parts[0] in self.section_aliases:
            return [self.content_section, *parts[1:]]
        return [self.content_section, *parts]

    def _resolve_output_dir(self, slug_parts: List[str]) -> str:
        if len(slug_parts) > 1:
            return os.path.join(self.content_dir, *slug_parts[:-1])
        return self.content_dir

    def _build_filename(self, basename: str, lang: Optional[str]) -> str:
        if not lang or not self.translation_default_language:
            return f"{basename}.md"
        if len(self.translation_languages) > 1:
            return f"{basename}.{lang}.md"
        if lang == self.translation_default_language:
            return f"{basename}.md"
        return f"{basename}.{lang}.md"

    def _render_markdown(self, front_matter: Dict[str, Any], content: str) -> str:
        return f"---\n{yaml.dump(front_matter, allow_unicode=True, default_flow_style=False)}---\n\n{content}"

    def _write_markdown(
        self,
        *,
        slug_parts: List[str],
        basename: str,
        lang: Optional[str],
        front_matter: Dict[str, Any],
        content: str,
    ) -> Optional[str]:
        output_dir = self._resolve_output_dir(slug_parts)
        os.makedirs(output_dir, exist_ok=True)
        filename = self._build_filename(basename, lang)
        file_path = os.path.join(output_dir, filename)
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(self._render_markdown(front_matter, content))
        return file_path

    def _resolve_source_language(self) -> Optional[str]:
        languages = list(dict.fromkeys(self.translation_languages))
        if not languages:
            return self.translation_default_language
        if self.translation_default_language:
            return self.translation_default_language
        return languages[0]

    def _build_source_path(
        self,
        *,
        slug_parts: List[str],
        slug_base: str,
        source_lang: str,
    ) -> str:
        source_filename = self._build_filename(slug_base, source_lang)
        output_dir_parts = slug_parts[:-1] if len(slug_parts) > 1 else []
        slug_dir = "/".join(output_dir_parts) if output_dir_parts else ""
        return f"{slug_dir}/{source_filename}" if slug_dir else source_filename

    def _generate_translations(
        self,
        *,
        post_id: Optional[str],
        slug_parts: List[str],
        slug_base: str,
        front_matter: Dict[str, Any],
        base_content: str,
        source_lang: Optional[str],
    ) -> bool:
        if not self.translation_languages or not self.translation_default_language:
            return True
        if not self.translation_service:
            return True

        languages = list(dict.fromkeys(self.translation_languages))
        if len(languages) <= 1:
            return True

        resolved_source_lang = (source_lang or "").strip()
        if not resolved_source_lang or resolved_source_lang not in languages:
            resolved_source_lang = languages[0]

        target_languages = [lang for lang in languages if lang != resolved_source_lang]
        if not target_languages:
            return True

        success = True

        for target_lang in target_languages:
            translation = self.translation_service.translate(
                resolved_source_lang,
                target_lang,
                front_matter.get("title", ""),
                base_content,
            )
            if not translation:
                logger.error(
                    "Failed to generate translation for %s -> %s (%s)",
                    resolved_source_lang,
                    target_lang,
                    front_matter.get("title", ""),
                )
                success = False
                continue

            translated_front_matter = dict(front_matter)
            translated_front_matter["title"] = translation.get("title", "")
            translated_front_matter["notion_source_language"] = resolved_source_lang
            translated_front_matter["notion_translation_language"] = target_lang

            source_path = self._build_source_path(
                slug_parts=slug_parts,
                slug_base=slug_base,
                source_lang=resolved_source_lang,
            )
            translated_front_matter["notion_source_path"] = source_path
            translated_content = translation.get("content", "").strip()
            translated_front_matter["summary"] = self._build_summary(
                language=target_lang,
                title=translated_front_matter["title"],
                content=translated_content,
            )

            file_path = self._write_markdown(
                slug_parts=slug_parts,
                basename=slug_base,
                lang=target_lang,
                front_matter=translated_front_matter,
                content=translated_content,
            )
            if file_path and self.cache_manager and post_id:
                self.cache_manager.record_content_path(post_id, file_path)

        return success

    def convert_post(self, post) -> bool:
        """Convert a Notion post into Hugo content files."""
        try:
            base_content = self.markdown_adapter.convert(post.content, page_title=post.title)
            slug_parts = self.normalize_slug_path(post.slug)
            slug_base = slug_parts[-1] if slug_parts else (post.slug.strip("/").strip() or post.id)
            source_lang = self._resolve_source_language()

            front_matter = {
                "title": post.title,
                "date": post.date.isoformat(),
                "lastmod": post.last_edited.isoformat(),
                "slug": slug_base,
                "tags": post.tags,
                "draft": False,
                "notion_id": post.id,
                "translationKey": post.id,
                "summary": self._build_summary(
                    language=source_lang,
                    title=post.title,
                    content=base_content,
                ),
            }

            if getattr(post, "categories", None):
                front_matter["categories"] = post.categories

            if post.cover_image:
                local_cover = self.media_handler.download_media(post.cover_image, "image")
                if local_cover:
                    front_matter["cover"] = {
                        "image": local_cover,
                        "alt": post.title,
                    }

            if self.cache_manager and post.id:
                self.cache_manager.clear_content_paths(post.id)

            file_path = self._write_markdown(
                slug_parts=slug_parts,
                basename=slug_base,
                lang=source_lang,
                front_matter=front_matter,
                content=base_content,
            )

            if file_path and self.cache_manager and post.id:
                self.cache_manager.record_content_path(post.id, file_path)

            translations_ok = self._generate_translations(
                post_id=post.id,
                slug_parts=slug_parts,
                slug_base=slug_base,
                front_matter=front_matter,
                base_content=base_content,
                source_lang=source_lang,
            )
            if not translations_ok:
                logger.error("One or more translations failed for %s", post.title)
                return False

            logger.info("Converted post: %s", post.title)
            return True
        except Exception as exc:
            logger.error("Error converting post %s: %s", post.title, exc)
            return False

    def _build_summary(self, *, language: Optional[str], title: str, content: str) -> str:
        if self.summary_service:
            try:
                summary = self.summary_service.summarize(language or "", title, content)
                if summary:
                    return summary
            except Exception as exc:
                logger.warning("Summary generation failed for %s: %s", title, exc)
        return self._fallback_summary(content)

    def _fallback_summary(self, content: str) -> str:
        if not content:
            return ""

        paragraphs: List[str] = []
        current_paragraph: List[str] = []
        in_code_fence = False
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line.startswith("```"):
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                continue
            if not line:
                if current_paragraph:
                    paragraphs.append(" ".join(current_paragraph))
                    current_paragraph = []
                continue
            if line.startswith("#") or line.startswith("{{<") or line.startswith("{{%"):
                continue
            if line.startswith("<aside") or line.startswith("</aside>"):
                continue
            current_paragraph.append(line)

        if current_paragraph:
            paragraphs.append(" ".join(current_paragraph))

        cleaned_paragraphs = [self._clean_summary_text(paragraph) for paragraph in paragraphs]
        cleaned_paragraphs = [paragraph for paragraph in cleaned_paragraphs if paragraph]
        if not cleaned_paragraphs:
            return ""

        plain = cleaned_paragraphs[0]
        for paragraph in cleaned_paragraphs[1:]:
            combined = f"{plain} {paragraph}".strip()
            if len(plain) >= 90 or len(combined) > 220:
                break
            plain = combined

        if len(plain) <= 220:
            return plain
        truncated = plain[:217].rsplit(" ", 1)[0].rstrip()
        return f"{truncated}..."

    def _clean_summary_text(self, text: str) -> str:
        plain = text or ""
        plain = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", plain)
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
        plain = re.sub(r"`([^`]+)`", r"\1", plain)
        plain = re.sub(r"<[^>]+>", " ", plain)
        return " ".join(plain.split())

    def clean_posts_directory(self):
        """Clean generated Notion posts from the content directory."""
        try:
            removed = 0
            base_dir = Path(self.content_dir).resolve()
            cache_paths = set()

            if self.cache_manager:
                for post_id, paths in self.cache_manager.get_all_content_paths().items():
                    for path in paths:
                        if path:
                            cache_paths.add(Path(path).resolve())
                    self.cache_manager.clear_content_paths(post_id)

            for path in cache_paths:
                if path.exists():
                    path.unlink()
                    removed += 1

            for md_path in base_dir.rglob("*.md"):
                if md_path in cache_paths:
                    continue
                if self._has_notion_front_matter(md_path):
                    md_path.unlink()
                    removed += 1

            logger.info("Cleaned %s generated markdown files", removed)
        except Exception as exc:
            logger.error("Error cleaning posts directory: %s", exc)

    def _has_notion_front_matter(self, path: Path) -> bool:
        try:
            with path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
                if not first_line.startswith("---"):
                    return False

                front_matter_lines = []
                for line in handle:
                    if line.startswith("---"):
                        break
                    front_matter_lines.append(line)

            front_matter = yaml.safe_load("".join(front_matter_lines)) or {}
            return bool(front_matter.get("notion_id"))
        except Exception:
            return False
