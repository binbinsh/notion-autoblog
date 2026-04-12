import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging
import requests
import yaml

logger = logging.getLogger(__name__)


class HugoConverter:
    def __init__(self, content_dir: str, media_handler, cache_manager=None):
        self.content_dir = content_dir
        self.media_handler = media_handler
        self.cache_manager = cache_manager
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
            translated_front_matter.pop("math", None)
            translated_front_matter.pop("mermaid", None)

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
            blocks = list(getattr(post, "blocks", []) or [])
            base_content = self._blocks_to_markdown(blocks)
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

            if self._has_math(blocks):
                front_matter["math"] = True

            if self._has_mermaid(blocks):
                front_matter["mermaid"] = True

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

    def _blocks_to_markdown(self, blocks: List[Dict[str, Any]]) -> str:
        markdown_parts: List[str] = []

        for block in blocks:
            markdown = self._convert_block(block)
            if markdown:
                markdown_parts.append(markdown)

        return "\n\n".join(markdown_parts)

    def _convert_block(self, block: Dict[str, Any]) -> str:
        block_type = block.get("type", "")

        try:
            if block_type == "paragraph":
                return self._convert_paragraph(block)
            if block_type.startswith("heading_"):
                return self._convert_heading(block)
            if block_type == "bulleted_list_item":
                return self._convert_list_item(block, "- ")
            if block_type == "numbered_list_item":
                return self._convert_list_item(block, "1. ")
            if block_type == "to_do":
                return self._convert_to_do(block)
            if block_type == "code":
                return self._convert_code(block)
            if block_type == "quote":
                return self._convert_quote(block)
            if block_type == "divider":
                return "---"
            if block_type == "image":
                return self._convert_image(block)
            if block_type == "video":
                return self._convert_video(block)
            if block_type == "audio":
                return self._convert_audio(block)
            if block_type == "equation":
                return self._convert_equation(block)
            if block_type == "toggle":
                return self._convert_toggle(block)
            if block_type == "callout":
                return self._convert_callout(block)
            if block_type == "bookmark":
                return self._convert_bookmark(block)
            if block_type == "embed":
                return self._convert_embed(block)
            if block_type == "table":
                return self._convert_table(block)
            if block_type == "column_list":
                return self._convert_column_list(block)
            if block_type == "link_preview":
                return self._convert_link_preview(block)
            if block_type == "child_page":
                return self._convert_child_page(block)
            if block_type == "pdf":
                return self._convert_pdf(block)
            if block_type == "file":
                return self._convert_file(block)
            if block_type == "table_of_contents":
                return "{{< toc >}}"
            if block_type == "column":
                return ""
            if block_type == "synced_block":
                return "<!-- Synced block -->"
            if block_type == "unsupported":
                return "<!-- Unsupported block type -->"
            logger.warning("Unsupported block type: %s", block_type)
            return ""
        except Exception as exc:
            logger.error("Error converting block type %s: %s", block_type, exc)
            return ""

    def _convert_paragraph(self, block: Dict[str, Any]) -> str:
        paragraph = block.get("paragraph", {})
        if not paragraph:
            return ""

        return self._rich_text_to_markdown(paragraph.get("rich_text", []))

    def _convert_heading(self, block: Dict[str, Any]) -> str:
        level = block["type"].split("_")[1]
        heading_data = block.get(block["type"], {})
        if not heading_data:
            return ""

        text = self._rich_text_to_markdown(heading_data.get("rich_text", []))
        block_id = (block.get("id") or "").replace("-", "").lower()
        if block_id:
            return f"{'#' * int(level)} {text} {{#{block_id}}}"
        return f"{'#' * int(level)} {text}"

    def _convert_list_item(self, block: Dict[str, Any], prefix: str) -> str:
        list_item = block.get(block["type"], {})
        if not list_item:
            return ""

        text = self._rich_text_to_markdown(list_item.get("rich_text", []))
        children = block.get("children", [])
        if children:
            child_content = []
            for child in children:
                child_text = self._convert_block(child)
                if child_text:
                    indented = "\n".join(f"    {line}" for line in child_text.split("\n"))
                    child_content.append(indented)
            if child_content:
                text += "\n" + "\n".join(child_content)

        return f"{prefix}{text}"

    def _convert_to_do(self, block: Dict[str, Any]) -> str:
        todo = block.get("to_do", {})
        if not todo:
            return ""

        text = self._rich_text_to_markdown(todo.get("rich_text", []))
        checked = "x" if todo.get("checked") else " "
        children = block.get("children", [])
        if children:
            child_content = []
            for child in children:
                child_text = self._convert_block(child)
                if child_text:
                    indented = "\n".join(f"    {line}" for line in child_text.split("\n"))
                    child_content.append(indented)
            if child_content:
                text += "\n" + "\n".join(child_content)

        return f"- [{checked}] {text}"

    def _convert_code(self, block: Dict[str, Any]) -> str:
        code_info = block.get("code", {})
        if not code_info:
            return ""

        language = code_info.get("language", "").lower()
        code_text = self._rich_text_to_plain_text(code_info.get("rich_text", []))

        mermaid_like = (
            "graph TD" in code_text
            or "flowchart" in code_text
            or "sequenceDiagram" in code_text
        )
        if not language and mermaid_like:
            language = "mermaid"

        return f"```{language}\n{code_text}\n```"

    def _convert_quote(self, block: Dict[str, Any]) -> str:
        quote = block.get("quote", {})
        if not quote:
            return ""

        text = self._rich_text_to_markdown(quote.get("rich_text", []))
        return "\n".join(f"> {line}" for line in text.split("\n"))

    def _get_block_last_edited_time(self, block: Dict[str, Any]) -> Optional[str]:
        return block.get("last_edited_time")

    def _convert_image(self, block: Dict[str, Any]) -> str:
        image_info = block.get("image", {})
        if not image_info:
            return ""

        if image_info.get("type") == "external":
            url = image_info.get("external", {}).get("url", "")
        else:
            url = image_info.get("file", {}).get("url", "")

        if not url:
            return ""

        last_edited_time = self._get_block_last_edited_time(block)
        local_path = self.media_handler.download_media(url, "image", last_edited_time)

        plain_caption = ""
        markdown_caption = ""
        if image_info.get("caption"):
            plain_caption = self._rich_text_to_plain_text(image_info["caption"])
            markdown_caption = self._rich_text_to_markdown(image_info["caption"])

        figure_content = f"<img src=\"{local_path}\" alt=\"{plain_caption}\">"
        if markdown_caption:
            figure_content += f"<figcaption>{markdown_caption}</figcaption>"
        return f"<figure>{figure_content}</figure>"

    def _convert_video(self, block: Dict[str, Any]) -> str:
        video_info = block.get("video", {})
        if not video_info:
            return ""

        video_style = "width: 100%; max-width: 100%; display: block; margin: 1.5rem 0;"

        if video_info.get("type") == "external":
            url = video_info.get("external", {}).get("url", "")
            if "youtube.com" in url or "youtu.be" in url:
                video_id = self._extract_youtube_id(url)
                if video_id:
                    return f'{{{{< youtube "{video_id}" >}}}}'
            if "vimeo.com" in url:
                video_id = url.split("/")[-1]
                return f'{{{{< vimeo "{video_id}" >}}}}'
            return f"<video controls style=\"{video_style}\">\n  <source src=\"{url}\">\n</video>"

        url = video_info.get("file", {}).get("url", "")
        if not url:
            return ""

        last_edited_time = self._get_block_last_edited_time(block)
        local_path = self.media_handler.download_media(url, "video", last_edited_time)
        return f"<video controls style=\"{video_style}\">\n  <source src=\"{local_path}\">\n</video>"

    def _convert_audio(self, block: Dict[str, Any]) -> str:
        audio_info = block.get("audio", {})
        if not audio_info:
            return ""

        if audio_info.get("type") == "external":
            url = audio_info.get("external", {}).get("url", "")
        else:
            url = audio_info.get("file", {}).get("url", "")
            if url:
                last_edited_time = self._get_block_last_edited_time(block)
                url = self.media_handler.download_media(url, "audio", last_edited_time)

        if not url:
            return ""

        return "<audio controls preload=\"none\" style=\"width: 100%;\">\n  <source src=\"%s\">\n</audio>" % url

    def _convert_equation(self, block: Dict[str, Any]) -> str:
        equation = block.get("equation", {})
        expression = equation.get("expression", "")
        if expression:
            return f"$$\n{expression}\n$$"
        return ""

    def _convert_toggle(self, block: Dict[str, Any]) -> str:
        toggle = block.get("toggle", {})
        if not toggle:
            return ""

        toggle_text = self._rich_text_to_markdown(toggle.get("rich_text", []))
        children = block.get("children", [])
        content = self._blocks_to_markdown(children) if children else ""
        return f"<details>\n<summary>{toggle_text}</summary>\n\n{content}\n</details>"

    def _convert_callout(self, block: Dict[str, Any]) -> str:
        callout = block.get("callout")
        if not callout:
            return ""

        icon = "💡"
        icon_obj = callout.get("icon")
        if icon_obj and isinstance(icon_obj, dict) and icon_obj.get("type") == "emoji":
            icon = icon_obj.get("emoji", "💡")

        text = self._rich_text_to_markdown(callout.get("rich_text", []))
        children = block.get("children", [])
        if children:
            child_content = self._blocks_to_markdown(children)
            if child_content:
                text += "\n\n" + child_content

        lines = text.split("\n")
        formatted_lines = [f"> {icon} "]
        formatted_lines.extend(f"> {line}" for line in lines)
        return "\n".join(formatted_lines)

    def _convert_bookmark(self, block: Dict[str, Any]) -> str:
        bookmark = block.get("bookmark", {})
        if not bookmark:
            return ""

        url = bookmark.get("url", "")
        if not url:
            return ""

        caption = ""
        if bookmark.get("caption"):
            caption = self._rich_text_to_plain_text(bookmark["caption"])

        link_text = caption or url
        escaped_text = self._escape_html(link_text)
        return f"- <a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{escaped_text}</a>"

    def _convert_table(self, block: Dict[str, Any]) -> str:
        table = block.get("table", {})
        if not table:
            return ""

        has_header = table.get("has_column_header", False)
        rows: List[List[str]] = []
        children = block.get("children", [])

        for child in children:
            if child.get("type") != "table_row":
                continue
            cells = child.get("table_row", {}).get("cells", [])
            rows.append([self._rich_text_to_markdown(cell) for cell in cells])

        if not rows:
            return ""

        def row_is_empty(row: List[str]) -> bool:
            return all(not cell.strip() for cell in row)

        if not has_header or row_is_empty(rows[0]):
            html_rows = []
            for row in rows:
                cells = "".join(f"<td>{cell}</td>" for cell in row)
                html_rows.append(f"<tr>{cells}</tr>")
            table_body = "\n".join(f"      {row}" for row in html_rows)
            return (
                "<div class=\"table-wrapper\">\n"
                "  <table>\n"
                "    <tbody>\n"
                f"{table_body}\n"
                "    </tbody>\n"
                "  </table>\n"
                "</div>"
            )

        markdown_lines = [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join(["---"] * len(rows[0])) + " |",
        ]
        for row in rows[1:]:
            markdown_lines.append("| " + " | ".join(row) + " |")
        return "\n".join(markdown_lines)

    def _convert_column_list(self, block: Dict[str, Any]) -> str:
        children = block.get("children", [])
        if not children:
            return ""

        all_content: List[str] = []
        image_count = 0

        for column in children:
            if column.get("type") != "column":
                continue

            column_children = column.get("children", [])
            column_has_only_images = bool(column_children) and all(
                child.get("type") == "image" for child in column_children
            )

            if column_has_only_images:
                for child in column_children:
                    image_info = child.get("image", {})
                    if not image_info:
                        continue
                    if image_info.get("type") == "external":
                        url = image_info.get("external", {}).get("url", "")
                    else:
                        url = image_info.get("file", {}).get("url", "")
                    if not url:
                        continue
                    child_last_edited_time = self._get_block_last_edited_time(child)
                    local_path = self.media_handler.download_media(
                        url,
                        "image",
                        child_last_edited_time,
                    )
                    caption = ""
                    if image_info.get("caption"):
                        caption = self._rich_text_to_plain_text(image_info["caption"])
                    figcaption = f"<figcaption>{caption}</figcaption>" if caption else ""
                    html = (
                        "<figure style=\"margin:0;\">\n"
                        f"  <img src=\"{local_path}\" alt=\"{caption}\" style=\"width:100%;height:auto;\">\n"
                        f"  {figcaption}\n"
                        "</figure>"
                    )
                    all_content.append(html)
                    image_count += 1
                continue

            column_content = self._blocks_to_markdown(column_children)
            if column_content:
                all_content.append(f"<div style=\"flex: 1;\">\n\n{column_content}\n\n</div>")

        if not all_content:
            return ""

        if image_count == len(all_content):
            return (
                "<div style=\"display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); "
                "gap: 20px; margin: 20px 0;\">\n"
                f"    {chr(10).join(all_content)}\n"
                "</div>"
            )

        return (
            "<div style=\"display: flex; gap: 20px; flex-wrap: wrap;\">\n"
            f"    {chr(10).join(all_content)}\n"
            "</div>"
        )

    def _convert_embed(self, block: Dict[str, Any]) -> str:
        embed_info = block.get("embed", {})
        url = embed_info.get("url", "")
        if not url:
            return ""

        if "twitter.com" in url or "x.com" in url:
            match = re.search(r"/status/(\d+)", url)
            if match:
                tweet_id = match.group(1)
                return f'{{{{< tweet user="user" id="{tweet_id}" >}}}}'

        if "youtube.com" in url or "youtu.be" in url:
            video_id = self._extract_youtube_id(url)
            if video_id:
                return f'{{{{< youtube "{video_id}" >}}}}'

        if "speakerdeck.com" in url:
            embed_html = self._speakerdeck_embed_html(url)
            if embed_html:
                return embed_html

        if "gist.github.com" in url:
            return f'{{{{< gist url="{url}" >}}}}'

        return f"<iframe src=\"{url}\" style=\"width:100%; height:400px;\"></iframe>"

    def _speakerdeck_embed_html(self, url: str) -> str:
        try:
            response = requests.get(
                "https://speakerdeck.com/oembed.json",
                params={"url": url},
                timeout=8,
            )
            if response.ok:
                data = response.json()
                raw_html = data.get("html", "")
                if raw_html:
                    src_match = re.search(r'src="([^"]+)"', raw_html)
                    src = src_match.group(1) if src_match else ""
                    if src:
                        return (
                            f"<iframe src=\"{src}\" "
                            "style=\"border:0;width:100%;aspect-ratio:16/9;height:auto;min-height:400px;\" "
                            "allowfullscreen loading=\"lazy\"></iframe>"
                        )
                    return raw_html
        except Exception as exc:
            logger.warning("SpeakerDeck embed fetch failed for %s: %s", url, exc)

        escaped_url = self._escape_html(url)
        return f"<a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{escaped_url}</a>"

    def _convert_link_preview(self, block: Dict[str, Any]) -> str:
        link_preview = block.get("link_preview", {})
        url = link_preview.get("url", "")
        if not url:
            return ""
        escaped_url = self._escape_html(url)
        return f"- <a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{escaped_url}</a>"

    def _convert_child_page(self, block: Dict[str, Any]) -> str:
        _ = block
        return ""

    def _convert_pdf(self, block: Dict[str, Any]) -> str:
        pdf_info = block.get("pdf", {})
        if not pdf_info:
            return ""

        if pdf_info.get("type") == "external":
            url = pdf_info.get("external", {}).get("url", "")
        else:
            url = pdf_info.get("file", {}).get("url", "")

        if not url:
            return ""

        last_edited_time = self._get_block_last_edited_time(block)
        local_path = self.media_handler.download_media(url, "pdf", last_edited_time)
        caption = ""
        if pdf_info.get("caption"):
            caption = self._rich_text_to_plain_text(pdf_info["caption"])
        title = caption or "PDF"
        return f"📄 [{title}]({local_path})"

    def _convert_file(self, block: Dict[str, Any]) -> str:
        file_info = block.get("file", {})
        if not file_info:
            return ""

        if file_info.get("type") == "external":
            url = file_info.get("external", {}).get("url", "")
        else:
            url = file_info.get("file", {}).get("url", "")

        if not url:
            return ""

        last_edited_time = self._get_block_last_edited_time(block)
        local_path = self.media_handler.download_media(url, "file", last_edited_time)
        caption = ""
        if file_info.get("caption"):
            caption = self._rich_text_to_plain_text(file_info["caption"])
        filename = caption or local_path.split("/")[-1]
        return f"📎 [{filename}]({local_path})"

    def _rich_text_to_markdown(self, rich_texts: List[Dict[str, Any]]) -> str:
        if not rich_texts:
            return ""

        result: List[str] = []

        for rich_text in rich_texts:
            text = rich_text.get("plain_text", "")
            annotations = rich_text.get("annotations", {})
            href = rich_text.get("href")
            notion_page_id = self._extract_page_id_from_url(href) if href else None
            local_href = None

            if href:
                pull_request = re.search(r"github\.com/.+?/pull/(\d+)", href)
                if pull_request:
                    pr_number = pull_request.group(1)
                    github_icon = (
                        "<img src=\"https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png\" "
                        "alt=\"GitHub\" style=\"display:inline-block; height:1.5em; vertical-align:middle;\">"
                    )
                    text = f"{github_icon} Pull Request #{pr_number}"
                    local_href = href

            if notion_page_id:
                resolved_title = self._lookup_page_title(notion_page_id)
                if resolved_title:
                    stripped_text = text.strip()
                    compact_id = notion_page_id.replace("-", "")
                    if (
                        not stripped_text
                        or stripped_text.lower() == "untitled"
                        or (href and stripped_text == href.strip())
                        or stripped_text in {notion_page_id, compact_id}
                    ):
                        text = resolved_title

            if href and local_href is None:
                local_href = self._rewrite_notion_link(href)

            if annotations.get("code"):
                text = f"<code>{self._escape_html(text)}</code>"
            else:
                if annotations.get("bold"):
                    text = f"<strong>{text}</strong>"
                if annotations.get("italic"):
                    text = f"<em>{text}</em>"
                if annotations.get("strikethrough"):
                    text = f"<del>{text}</del>"
                if annotations.get("underline"):
                    text = f"<u>{text}</u>"

            color = annotations.get("color", "default")
            if color != "default":
                text = f"<span style=\"color: {color}\">{text}</span>"

            if local_href:
                href_attr = self._escape_html_attr(local_href)
                is_external = (
                    local_href.startswith("http://")
                    or local_href.startswith("https://")
                    or local_href.startswith("//")
                )
                if is_external and not local_href.startswith("/") and not local_href.startswith("#"):
                    text = (
                        f"<a href='{href_attr}' target='_blank' rel='noopener noreferrer'>"
                        f"{text}</a>"
                    )
                else:
                    text = f"<a href='{href_attr}'>{text}</a>"

            result.append(text)

        return "".join(result)

    def _rich_text_to_plain_text(self, rich_texts: List[Dict[str, Any]]) -> str:
        if not rich_texts:
            return ""
        return "".join(rich_text.get("plain_text", "") for rich_text in rich_texts)

    def _escape_html(self, value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _escape_html_attr(self, value: str) -> str:
        return (value or "").replace("'", "&#39;")

    def _lookup_page_title(self, page_id: str) -> Optional[str]:
        if not page_id:
            return None
        compact_id = page_id.replace("-", "")
        return self.id_to_title.get(page_id) or self.id_to_title.get(compact_id)

    def _extract_page_id_from_url(self, url: str) -> Optional[str]:
        try:
            url_without_fragment = (url or "").split("#", 1)[0]
            patterns = [
                r"([0-9a-f]{32})$",
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
                r"([0-9a-f]{32})(?:\?.*)?$",
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\?.*)?$",
            ]
            for pattern in patterns:
                match = re.search(pattern, url_without_fragment, re.IGNORECASE)
                if match:
                    return match.group(1)
        except Exception:
            return None
        return None

    def _rewrite_notion_link(self, url: str) -> str:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            fragment = (parsed.fragment or "").strip()

            if (url.startswith("#") or (not parsed.scheme and not parsed.netloc and not parsed.path)) and fragment:
                if re.fullmatch(r"[0-9a-fA-F\-]{36}", fragment) or re.fullmatch(r"[0-9a-fA-F]{32}", fragment):
                    return f"#{fragment.replace('-', '').lower()}"
                return f"#{fragment}"

            matched_id = self._extract_page_id_from_url(url)
            if matched_id and self.id_to_slug:
                slug = self.id_to_slug.get(matched_id) or self.id_to_slug.get(matched_id.replace("-", ""))
                if slug:
                    slug_parts = self.normalize_slug_path(slug)
                    slug_base = slug_parts[-1] if slug_parts else slug.strip("/").strip()
                    slug_dir = "/".join(slug_parts[:-1]) if len(slug_parts) > 1 else ""
                    relref_path = f"{slug_dir}/{slug_base}.md" if slug_dir else f"{slug_base}.md"
                    relref = f'{{{{< relref path="{relref_path}" >}}}}'

                    if fragment:
                        if re.fullmatch(r"[0-9a-fA-F\-]{36}", fragment) or re.fullmatch(r"[0-9a-fA-F]{32}", fragment):
                            return f"{relref}#{fragment.replace('-', '').lower()}"
                        return f"{relref}#{fragment}"
                    return relref
        except Exception:
            return url
        return url

    def _has_mermaid(self, blocks: List[Dict[str, Any]]) -> bool:
        for block in blocks:
            if block.get("type") == "code":
                code_info = block.get("code", {})
                language = code_info.get("language", "").lower()
                if language == "mermaid":
                    return True
                text = self._rich_text_to_plain_text(code_info.get("rich_text", []))
                if "graph TD" in text or "flowchart" in text or "sequenceDiagram" in text:
                    return True
            if block.get("children") and self._has_mermaid(block["children"]):
                return True
        return False

    def _has_math(self, blocks: List[Dict[str, Any]]) -> bool:
        for block in blocks:
            if block.get("type") == "equation":
                return True

            block_type = block.get("type", "")
            if block_type in {"paragraph", "bulleted_list_item", "numbered_list_item", "to_do"}:
                block_data = block.get(block_type, {})
                text_content = self._rich_text_to_plain_text(block_data.get("rich_text", []))
                if "$" in text_content or "\\(" in text_content or "\\[" in text_content:
                    return True

            if block.get("children") and self._has_math(block["children"]):
                return True

        return False

    def _extract_youtube_id(self, url: str) -> str:
        patterns = [
            r"(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)",
            r"youtube\.com\/embed\/([^&\n?#]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return ""

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

            for markdown_path in base_dir.rglob("*.md"):
                if markdown_path in cache_paths:
                    continue
                if self._has_notion_front_matter(markdown_path):
                    markdown_path.unlink()
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
