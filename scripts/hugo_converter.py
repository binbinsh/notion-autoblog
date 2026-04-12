import os
import re
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import requests

logger = logging.getLogger(__name__)

class HugoConverter:
    def __init__(self, content_dir: str, media_handler, cache_manager=None):
        self.content_dir = content_dir
        self.media_handler = media_handler
        self.cache_manager = cache_manager
        os.makedirs(self.content_dir, exist_ok=True)
        self.id_to_slug = {}
        self.id_to_title = {}
        self.translation_languages = []
        self.translation_default_language = None
        self.translation_service = None

    def set_translation_config(self, target_languages: List[str], translator=None):
        self.translation_languages = target_languages or []
        self.translation_default_language = self.translation_languages[0] if self.translation_languages else None
        self.translation_service = translator

    def set_id_to_slug_mapping(self, mapping: Dict[str, str], title_mapping: Optional[Dict[str, str]] = None):
        self.id_to_slug = mapping or {}
        self.id_to_title = title_mapping or {}

    def normalize_slug_path(self, slug: str) -> List[str]:
        if not slug:
            return []
        cleaned = slug.strip()
        if not cleaned:
            return []
        cleaned = cleaned.lstrip("/").strip("/")
        parts = [part for part in cleaned.split("/") if part]
        return parts

    def _resolve_output_dir(self, slug_parts: List[str]) -> str:
        if len(slug_parts) > 1:
            rel_parts = slug_parts[:-1]
            return os.path.join(self.content_dir, *rel_parts)
        return self.content_dir

    def _build_filename(self, basename: str, lang: Optional[str]) -> str:
        # Hugo "translation by file name": when multilingual, always include suffixes.
        if not lang or not self.translation_default_language:
            return f"{basename}.md"
        if len(self.translation_languages) > 1:
            return f"{basename}.{lang}.md"
        if lang == self.translation_default_language:
            return f"{basename}.md"
        return f"{basename}.{lang}.md"

    def _render_markdown(self, front_matter: Dict[str, Any], content: str) -> str:
        file_content = "---\n"
        file_content += yaml.dump(front_matter, allow_unicode=True, default_flow_style=False)
        file_content += "---\n\n"
        file_content += content
        return file_content

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
        file_content = self._render_markdown(front_matter, content)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(file_content)
        return file_path

    def _resolve_source_language(self) -> Optional[str]:
        languages = list(dict.fromkeys(self.translation_languages))
        if not languages:
            return self.translation_default_language
        if self.translation_default_language:
            return self.translation_default_language
        return languages[0]

    def _language_display_name(self, lang: str) -> str:
        """Return a human-friendly language name for a language code.

        This is used only for end-user visible notices; internal Hugo language codes
        (e.g. `lang="zh"`) should remain unchanged.
        """
        key = (lang or "").strip().lower()
        if not key:
            return ""

        # Normalize common variants (e.g. zh-cn -> zh).
        base = key.split("-", 1)[0]
        mapping = {
            "zh": "Chinese",
            "en": "English",
        }
        return mapping.get(key) or mapping.get(base) or lang

    def _build_translation_notice(self, slug_parts: List[str], slug_base: str, source_lang: str) -> str:
        if not source_lang:
            return ""
        # Point to the actual source filename (suffixes when multilingual is enabled).
        source_filename = self._build_filename(slug_base, source_lang)
        output_dir_parts = slug_parts[:-1] if len(slug_parts) > 1 else []
        slug_dir = "/".join(output_dir_parts) if output_dir_parts else ""
        relref_path = f"{slug_dir}/{source_filename}" if slug_dir else source_filename
        relref = f'{{{{< relref path=\"{relref_path}\" lang=\"{source_lang}\" >}}}}'
        source_label = self._escape_html(self._language_display_name(source_lang) or source_lang)
        return (
            "<aside class=\"notion-translation-note\" role=\"note\" style=\""
            "margin: 1rem 0; padding: .75rem 1rem; "
            "border: 1px solid rgba(59, 130, 246, 0.25); border-left: 4px solid #3b82f6; "
            "border-radius: 10px; background: rgba(59, 130, 246, 0.08); "
            "font-style: normal;\">"
            f"<strong>Note:</strong> Machine-translated from the "
            f"<a href='{relref}'>{source_label} original</a>."
            "</aside>"
        )

    def _generate_translations(
        self,
        *,
        post_id: Optional[str],
        slug_parts: List[str],
        slug_base: str,
        front_matter: Dict[str, Any],
        content: str,
        source_lang: Optional[str],
    ) -> None:
        if not self.translation_languages or not self.translation_default_language:
            return
        if not self.translation_service:
            return
    
        languages = list(dict.fromkeys(self.translation_languages))
        if len(languages) <= 1:
            return
    
        resolved_source_lang = (source_lang or "").strip()
        if not resolved_source_lang or resolved_source_lang not in languages:
            resolved_source_lang = languages[0]
    
        target_languages = [lang for lang in languages if lang != resolved_source_lang]
        if not target_languages:
            return
    
        for target_lang in target_languages:
            translation = self.translation_service.translate(
                resolved_source_lang,
                target_lang,
                front_matter.get("title", ""),
                content,
            )
            if not translation:
                continue
    
            translated_front_matter = dict(front_matter)
            translated_front_matter["title"] = translation.get("title", "")
            translated_front_matter["notion_source_language"] = resolved_source_lang
            translated_front_matter["notion_translation_language"] = target_lang
    
            notice = self._build_translation_notice(
                slug_parts,
                slug_base,
                resolved_source_lang,
            )
            translated_content = translation.get("content", "")
            if notice:
                translated_content = f"{notice}\n\n{translated_content}"
    
            file_path = self._write_markdown(
                slug_parts=slug_parts,
                basename=slug_base,
                lang=target_lang,
                front_matter=translated_front_matter,
                content=translated_content,
            )
            if file_path and self.cache_manager and post_id:
                self.cache_manager.record_content_path(post_id, file_path)

    def convert_post(self, post) -> bool:
        """Convert a Notion post into Hugo format"""
        try:
            # Convert content
            content = self._blocks_to_markdown(post.blocks)

            # Create front matter
            slug_parts = self.normalize_slug_path(post.slug)
            slug_base = slug_parts[-1] if slug_parts else (post.slug.strip("/").strip() or post.id)
            source_lang = self._resolve_source_language()
            front_matter = {
                'title': post.title,
                'date': post.date.isoformat(),
                'lastmod': post.last_edited.isoformat(),
                'slug': slug_base,
                'tags': post.tags,
                'draft': False,
                'math': self._has_math(post.blocks),  # Check if it contains math formulas
                'notion_id': post.id,
            }

            if getattr(post, 'categories', None):
                front_matter['categories'] = post.categories

            # Enable Mermaid when needed
            if self._has_mermaid(post.blocks):
                front_matter['mermaid'] = True

            # Add cover image
            if post.cover_image:
                local_cover = self.media_handler.download_media(post.cover_image, "image")
                if local_cover:
                    front_matter['cover'] = {
                        'image': local_cover,
                        'alt': post.title
                    }

            if self.cache_manager and post.id:
                self.cache_manager.clear_content_paths(post.id)

            file_path = self._write_markdown(
                slug_parts=slug_parts,
                basename=slug_base,
                lang=source_lang,
                front_matter=front_matter,
                content=content,
            )

            if file_path and self.cache_manager and post.id:
                self.cache_manager.record_content_path(post.id, file_path)

            self._generate_translations(
                post_id=post.id,
                slug_parts=slug_parts,
                slug_base=slug_base,
                front_matter=front_matter,
                content=content,
                source_lang=source_lang,
            )

            logger.info(f"Converted post: {post.title}")
            return True

        except Exception as e:
            logger.error(f"Error converting post {post.title}: {e}")
            return False

    def _blocks_to_markdown(self, blocks: List[Dict[str, Any]]) -> str:
        """Convert Notion blocks to Markdown"""
        markdown_parts = []

        for block in blocks:
            block_type = block.get('type', '')
            markdown = self._convert_block(block)
            if markdown:
                markdown_parts.append(markdown)

        return '\n\n'.join(markdown_parts)

    def _convert_block(self, block: Dict[str, Any]) -> str:
        """Convert a single block"""
        block_type = block.get('type', '')

        try:
            if block_type == 'paragraph':
                return self._convert_paragraph(block)
            elif block_type.startswith('heading_'):
                return self._convert_heading(block)
            elif block_type == 'bulleted_list_item':
                return self._convert_list_item(block, '- ')
            elif block_type == 'numbered_list_item':
                return self._convert_list_item(block, '1. ')
            elif block_type == 'code':
                return self._convert_code(block)
            elif block_type == 'quote':
                return self._convert_quote(block)
            elif block_type == 'divider':
                return '---'
            elif block_type == 'image':
                return self._convert_image(block)
            elif block_type == 'video':
                return self._convert_video(block)
            elif block_type == 'audio':
                return self._convert_audio(block)
            elif block_type == 'equation':
                return self._convert_equation(block)
            elif block_type == 'toggle':
                return self._convert_toggle(block)
            elif block_type == 'callout':
                return self._convert_callout(block)
            elif block_type == 'bookmark':
                return self._convert_bookmark(block)
            elif block_type == 'embed':
                return self._convert_embed(block)
            elif block_type == 'table':
                return self._convert_table(block)
            elif block_type == 'column_list':
                return self._convert_column_list(block)
            elif block_type == 'link_preview':
                return self._convert_link_preview(block)
            elif block_type == 'child_page':
                return self._convert_child_page(block)
            elif block_type == 'pdf':
                return self._convert_pdf(block)
            elif block_type == 'file':
                return self._convert_file(block)
            elif block_type == 'table_of_contents':
                return "{{< toc >}}"
            elif block_type == 'column':
                # Column blocks are handled by column_list
                return ""
            elif block_type == 'synced_block':
                return "<!-- Synced block -->"
            elif block_type == 'unsupported':
                return "<!-- Unsupported block type -->"
            else:
                logger.warning(f"Unsupported block type: {block_type}")
                return ""
        except Exception as e:
            logger.error(f"Error converting block type {block_type}: {e}")
            return ""

    def _convert_paragraph(self, block: Dict[str, Any]) -> str:
        """Convert paragraph"""
        paragraph = block.get('paragraph', {})
        if not paragraph:
            return ""

        rich_text = paragraph.get('rich_text', [])
        text = self._rich_text_to_markdown(rich_text)
        return text if text else ""

    def _convert_heading(self, block: Dict[str, Any]) -> str:
        """Convert heading"""
        level = block['type'].split('_')[1]
        heading_data = block.get(block['type'], {})
        if not heading_data:
            return ""

        text = self._rich_text_to_markdown(heading_data.get('rich_text', []))

        # Use Notion block id as a stable anchor so intra-post links work reliably.
        # Normalize to compact lowercase hex without dashes to match Notion-style fragments.
        block_id = (block.get('id') or '').replace('-', '').lower()
        if block_id:
            return f"{'#' * int(level)} {text} {{#{block_id}}}"
        return f"{'#' * int(level)} {text}"

    def _convert_list_item(self, block: Dict[str, Any], prefix: str) -> str:
        """Convert list item"""
        list_item = block.get(block['type'], {})
        if not list_item:
            return ""

        text = self._rich_text_to_markdown(list_item.get('rich_text', []))

        # Handle child items
        children = block.get('children', [])
        if children:
            child_content = []
            for child in children:
                child_text = self._convert_block(child)
                if child_text:
                    # Indent child items by 4 spaces so Goldmark treats them as part of the same list item.
                    # This preserves ordered list numbering and keeps nested bullets/numbered lists.
                    indented = '\n'.join(f"    {line}" for line in child_text.split('\n'))
                    child_content.append(indented)

            if child_content:
                text += '\n' + '\n'.join(child_content)

        return f"{prefix}{text}"

    def _convert_code(self, block: Dict[str, Any]) -> str:
        """Convert code block"""
        code_info = block.get('code', {})
        if not code_info:
            return ""

        language = code_info.get('language', '').lower()
        code_text = self._rich_text_to_plain_text(code_info.get('rich_text', []))

        # Detect Mermaid even if language wasn't set explicitly in Notion
        mermaid_like = ('graph TD' in code_text) or ('flowchart' in code_text) or ('sequenceDiagram' in code_text)
        if not language and mermaid_like:
            language = 'mermaid'

        return f"```{language}\n{code_text}\n```"

    def _convert_quote(self, block: Dict[str, Any]) -> str:
        """Convert quote"""
        quote = block.get('quote', {})
        if not quote:
            return ""

        text = self._rich_text_to_markdown(quote.get('rich_text', []))
        lines = text.split('\n')
        return '\n'.join(f"> {line}" for line in lines)
    
    def _get_block_last_edited_time(self, block: Dict[str, Any]) -> Optional[str]:
        """Extract last_edited_time from a block if available"""
        return block.get('last_edited_time')

    def _convert_image(self, block: Dict[str, Any]) -> str:
        """Convert image"""
        image_info = block.get('image', {})
        if not image_info:
            return ""

        if image_info.get('type') == 'external':
            url = image_info.get('external', {}).get('url', '')
        else:
            url = image_info.get('file', {}).get('url', '')

        if not url:
            return ""

        # Download image with last_edited_time for cache invalidation
        last_edited_time = self._get_block_last_edited_time(block)
        local_path = self.media_handler.download_media(url, "image", last_edited_time)

        # Get caption
        caption = ""
        if image_info.get('caption'):
            caption = self._rich_text_to_plain_text(image_info['caption'])

        return f"![{caption}]({local_path})"

    def _convert_video(self, block: Dict[str, Any]) -> str:
        """Convert video"""
        video_info = block.get('video', {})
        if not video_info:
            return ""

        # Keep video width aligned with the content column instead of shrinking it.
        video_style = "width: 100%; max-width: 100%; display: block; margin: 1.5rem 0;"

        if video_info.get('type') == 'external':
            url = video_info.get('external', {}).get('url', '')
            # Handle external video providers like YouTube/Vimeo
            if 'youtube.com' in url or 'youtu.be' in url:
                video_id = self._extract_youtube_id(url)
                if video_id:
                    return f'{{{{< youtube "{video_id}" >}}}}'
            elif 'vimeo.com' in url:
                video_id = url.split('/')[-1]
                return f'{{{{< vimeo "{video_id}" >}}}}'
            else:
                return f'<video controls style="{video_style}">\n  <source src="{url}">\n</video>'
        else:
            # Download video file
            url = video_info.get('file', {}).get('url', '')
            if url:
                last_edited_time = self._get_block_last_edited_time(block)
                local_path = self.media_handler.download_media(url, "video", last_edited_time)
                return f'<video controls style="{video_style}">\n  <source src="{local_path}">\n</video>'

        return ""

    def _convert_audio(self, block: Dict[str, Any]) -> str:
        """Convert audio"""
        audio_info = block.get('audio', {})
        if not audio_info:
            return ""

        if audio_info.get('type') == 'external':
            url = audio_info.get('external', {}).get('url', '')
        else:
            url = audio_info.get('file', {}).get('url', '')
            if url:
                # Download audio file
                last_edited_time = self._get_block_last_edited_time(block)
                local_path = self.media_handler.download_media(url, "audio", last_edited_time)
                url = local_path

        if url:
            return f'<audio controls preload="none" style="width: 100%;">\n  <source src="{url}">\n</audio>'
        return ""

    def _convert_equation(self, block: Dict[str, Any]) -> str:
        """Convert mathematical equation"""
        equation = block.get('equation', {})
        expression = equation.get('expression', '')
        if expression:
            # Use $$ to wrap block-level formulas
            return f"$$\n{expression}\n$$"
        return ""

    def _convert_toggle(self, block: Dict[str, Any]) -> str:
        """Convert toggle block"""
        toggle = block.get('toggle', {})
        if not toggle:
            return ""

        toggle_text = self._rich_text_to_markdown(toggle.get('rich_text', []))

        # Get child content
        children = block.get('children', [])
        content = ""
        if children:
            content = self._blocks_to_markdown(children)

        # Hugo doesn't directly support toggle, use details tag
        return f"<details>\n<summary>{toggle_text}</summary>\n\n{content}\n</details>"

    def _convert_callout(self, block: Dict[str, Any]) -> str:
        """Convert callout block"""
        callout = block.get('callout')
        if not callout:
            return ""

        # Safely get icon
        icon = '💡'
        icon_obj = callout.get('icon')
        if icon_obj and isinstance(icon_obj, dict):
            if icon_obj.get('type') == 'emoji':
                icon = icon_obj.get('emoji', '💡')

        text = self._rich_text_to_markdown(callout.get('rich_text', []))

        # Get child content
        children = block.get('children', [])
        if children:
            child_content = self._blocks_to_markdown(children)
            if child_content:
                text += '\n\n' + child_content

        # Use blockquote style
        lines = text.split('\n')
        formatted_lines = [f"> {icon} "]
        formatted_lines.extend(f"> {line}" for line in lines)

        return '\n'.join(formatted_lines)

    def _convert_bookmark(self, block: Dict[str, Any]) -> str:
        """Convert bookmark"""
        bookmark = block.get('bookmark', {})
        if not bookmark:
            return ""

        url = bookmark.get('url', '')
        if not url:
            return ""

        # Get title
        caption = ""
        if bookmark.get('caption'):
            caption = self._rich_text_to_plain_text(bookmark['caption'])

        # Always return as HTML anchor so we can control target
        link_text = caption or url
        return f"- <a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{self._escape_html(link_text)}</a>"

    def _convert_table(self, block: Dict[str, Any]) -> str:
        """Convert table"""
        table = block.get('table', {})
        if not table:
            return ""

        has_header = table.get('has_column_header', False)

        # Get table rows
        rows = []
        children = block.get('children', [])

        for child in children:
            if child.get('type') == 'table_row':
                row_data = child.get('table_row', {})
                cells = row_data.get('cells', [])
                row = []
                for cell in cells:
                    cell_text = self._rich_text_to_markdown(cell)
                    row.append(cell_text)
                rows.append(row)

        if not rows:
            return ""

        def _row_is_empty(row: List[str]) -> bool:
            return all(not cell.strip() for cell in row)

        # If Notion didn't mark a header (or the header row is empty), emit raw HTML
        # wrapped in the same structure our Hugo render hook uses so tables keep
        # consistent styling (responsive scrolling, borders, etc.).
        if not has_header or _row_is_empty(rows[0]):
            html_rows = []
            for row in rows:
                cells = ''.join(f"<td>{cell}</td>" for cell in row)
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

        # Generate Markdown table when a real header exists
        markdown_lines = []

        # Table header
        markdown_lines.append('| ' + ' | '.join(rows[0]) + ' |')
        markdown_lines.append('| ' + ' | '.join(['---'] * len(rows[0])) + ' |')
        rows = rows[1:]

        # Table content
        for row in rows:
            markdown_lines.append('| ' + ' | '.join(row) + ' |')

        return '\n'.join(markdown_lines)

    def _convert_column_list(self, block: Dict[str, Any]) -> str:
        """Convert column layout"""
        children = block.get('children', [])
        if not children:
            return ""

        # Collect all content in columns
        all_content = []
        image_count = 0

        for column in children:
            if column.get('type') == 'column':
                column_children = column.get('children', [])

                # Check if this column only contains images
                column_has_only_images = all(
                    child.get('type') == 'image'
                    for child in column_children
                )

                if column_has_only_images and column_children:
                    # If column only contains images, handle each image separately
                    for child in column_children:
                        image_info = child.get('image', {})
                        if not image_info:
                            continue
                        # Resolve URL
                        if image_info.get('type') == 'external':
                            url = image_info.get('external', {}).get('url', '')
                        else:
                            url = image_info.get('file', {}).get('url', '')
                        if not url:
                            continue
                        # Download and build HTML directly so Markdown is not nested inside HTML
                        child_last_edited_time = self._get_block_last_edited_time(child)
                        local_path = self.media_handler.download_media(url, "image", child_last_edited_time)
                        caption = ""
                        if image_info.get('caption'):
                            caption = self._rich_text_to_plain_text(image_info['caption'])
                        figcaption = f"<figcaption>{caption}</figcaption>" if caption else ""
                        html = (
                            f"<figure style=\"margin:0;\">\n"
                            f"  <img src=\"{local_path}\" alt=\"{caption}\" style=\"width:100%;height:auto;\">\n"
                            f"  {figcaption}\n"
                            f"</figure>"
                        )
                        all_content.append(html)
                        image_count += 1
                else:
                    # Otherwise, handle column content normally
                    column_content = self._blocks_to_markdown(column_children)
                    if column_content:
                        all_content.append(f'<div style="flex: 1;">\\n\\n{column_content}\\n\\n</div>')

        # If all columns are images, use image grid layout
        if image_count == len(all_content):
            return f'''<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0;">
    {chr(10).join(all_content)}
    </div>'''

        # Otherwise, use normal flex layout
        return f'''<div style="display: flex; gap: 20px; flex-wrap: wrap;">
    {chr(10).join(all_content)}
    </div>'''

    def _convert_image(self, block: Dict[str, Any]) -> str:
        """Convert image"""
        image_info = block.get('image', {})
        if not image_info:
            return ""

        if image_info.get('type') == 'external':
            url = image_info.get('external', {}).get('url', '')
        else:
            url = image_info.get('file', {}).get('url', '')

        if not url:
            return ""

        # Download image with last_edited_time for cache invalidation
        last_edited_time = self._get_block_last_edited_time(block)
        local_path = self.media_handler.download_media(url, "image", last_edited_time)

        # Get caption (plain for alt, markdown for figcaption)
        plain_caption = ""
        md_caption = ""
        if image_info.get('caption'):
            plain_caption = self._rich_text_to_plain_text(image_info['caption'])
            md_caption = self._rich_text_to_markdown(image_info['caption'])

        # Build HTML for image with optional alignment wrapper
        img_html = f"<img src=\"{local_path}\" alt=\"{plain_caption}\">"
        figure_content = img_html
        if md_caption:
            figure_content += f"<figcaption>{md_caption}</figcaption>"
        return f"<figure>{figure_content}</figure>"

    def _convert_embed(self, block: Dict[str, Any]) -> str:
        """Convert embedded content"""
        embed_info = block.get('embed', {})
        url = embed_info.get('url', '')

        if not url:
            return ""

        # Twitter/X embed
        if 'twitter.com' in url or 'x.com' in url:
            # Extract tweet ID
            match = re.search(r'/status/(\\d+)', url)
            if match:
                tweet_id = match.group(1)
                return f'{{{{< tweet user="user" id="{tweet_id}" >}}}}'

        # YouTube
        elif 'youtube.com' in url or 'youtu.be' in url:
            video_id = self._extract_youtube_id(url)
            if video_id:
                return f'{{{{< youtube "{video_id}" >}}}}'

        # Speaker Deck
        elif 'speakerdeck.com' in url:
            embed_html = self._speakerdeck_embed_html(url)
            if embed_html:
                return embed_html

        # GitHub Gist
        elif 'gist.github.com' in url:
            return f'{{{{< gist url="{url}" >}}}}'

        # CodePen
        elif 'codepen.io' in url:
            return f'<iframe src="{url}" style="width:100%; height:400px;"></iframe>'

        # Generic iframe
        else:
            return f'<iframe src="{url}" style="width:100%; height:400px;"></iframe>'

    def _speakerdeck_embed_html(self, url: str) -> str:
        """Resolve Speaker Deck URLs to embeddable player if possible."""
        try:
            resp = requests.get(
                "https://speakerdeck.com/oembed.json",
                params={"url": url},
                timeout=8,
            )
            if resp.ok:
                data = resp.json()
                raw_html = data.get("html", "")
                if raw_html:
                    src_match = re.search(r'src="([^"]+)"', raw_html)
                    src = src_match.group(1) if src_match else ""
                    if src:
                        return (
                            f'<iframe src="{src}" '
                            'style="border:0;width:100%;aspect-ratio:16/9;height:auto;min-height:400px;" '
                            'allowfullscreen loading="lazy"></iframe>'
                        )
                    return raw_html
        except Exception as e:
            logger.warning(f"SpeakerDeck embed fetch failed for {url}: {e}")

        # Fallback to a clickable link when we can't embed
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{self._escape_html(url)}</a>'

    def _convert_link_preview(self, block: Dict[str, Any]) -> str:
        """Convert link preview"""
        link_preview = block.get('link_preview', {})
        url = link_preview.get('url', '')

        if url:
            return f"- <a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{self._escape_html(url)}</a>"
        return ""

    def _convert_child_page(self, block: Dict[str, Any]) -> str:
        """Convert child page reference"""
        child_page = block.get('child_page', {})
        title = child_page.get('title', 'Child Page')
        # Avoid verbose placeholders; omit unless we can link to a local page.
        return ""

    def _convert_pdf(self, block: Dict[str, Any]) -> str:
        """Convert PDF"""
        pdf_info = block.get('pdf', {})
        if not pdf_info:
            return ""

        if pdf_info.get('type') == 'external':
            url = pdf_info.get('external', {}).get('url', '')
        else:
            url = pdf_info.get('file', {}).get('url', '')

        if not url:
            return ""

        # Get title
        caption = ""
        if pdf_info.get('caption'):
            caption = self._rich_text_to_plain_text(pdf_info['caption'])

        title = caption or "PDF Document"

        return f'📄 [{title}]({url})'

    def _convert_file(self, block: Dict[str, Any]) -> str:
        """Convert file"""
        file_info = block.get('file', {})
        if not file_info:
            return ""

        if file_info.get('type') == 'external':
            url = file_info.get('external', {}).get('url', '')
        else:
            url = file_info.get('file', {}).get('url', '')

        if not url:
            return ""

        # Get filename
        caption = ""
        if file_info.get('caption'):
            caption = self._rich_text_to_plain_text(file_info['caption'])

        filename = caption or url.split('/')[-1]

        return f'📎 [{filename}]({url})'

    def _rich_text_to_markdown(self, rich_texts: List[Dict[str, Any]]) -> str:
        """Convert rich text to Markdown"""
        if not rich_texts:
            return ""

        result = []

        for rt in rich_texts:
            text = rt.get('plain_text', '')
            annotations = rt.get('annotations', {})
            href = rt.get('href')
            notion_page_id = self._extract_page_id_from_url(href) if href else None
            local_href = None

            # Detect GitHub PR URLs and format as friendly link
            if href:
                m = re.search(r'github\.com/.+?/pull/(\d+)', href)
                if m:
                    pr_number = m.group(1)
                    # Use GitHub icon with friendly text
                    gh_icon = '<img src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png" alt="GitHub" style="display:inline-block; height:1.5em; vertical-align:middle;">'
                    text = f"{gh_icon} Pull Request #{pr_number}"
                    # Keep the original URL for link target
                    local_href = href
                    is_external = True

            # Replace placeholder link text (e.g., Untitled) with the real page title
            if notion_page_id:
                resolved_title = self._lookup_page_title(notion_page_id)
                if resolved_title:
                    stripped_text = text.strip()
                    compact_id = notion_page_id.replace('-', '')
                    if (
                        not stripped_text
                        or stripped_text.lower() == 'untitled'
                        or (href and stripped_text == href.strip())
                        or stripped_text in {notion_page_id, compact_id}
                    ):
                        text = resolved_title

            # Rewrite Notion links to local Hugo slugs if possible (skip for GitHub PR URLs)
            if href:
                if re.search(r'github\.com/.+?/pull/\d+', href):
                    local_href = href
                else:
                    local_href = self._rewrite_notion_link(href)
            else:
                local_href = None

            # Build formatting using HTML to avoid conflicts when wrapped inside HTML spans
            # and to ensure consistent rendering by Goldmark.
            if annotations.get('code'):
                text = f"<code>{self._escape_html(text)}</code>"
            else:
                if annotations.get('bold'):
                    text = f"<strong>{text}</strong>"
                if annotations.get('italic'):
                    text = f"<em>{text}</em>"
                if annotations.get('strikethrough'):
                    text = f"<del>{text}</del>"
                if annotations.get('underline'):
                    text = f"<u>{text}</u>"

            color = annotations.get('color', 'default')
            if color != 'default':
                text = f'<span style="color: {color}">{text}</span>'

            if local_href:
                href_attr = self._escape_html_attr(local_href)
                is_external = (
                    local_href.startswith('http://') or
                    local_href.startswith('https://') or
                    local_href.startswith('//')
                )
                if is_external and not local_href.startswith('/') and not local_href.startswith('#'):
                    text = f"<a href='{href_attr}' target='_blank' rel='noopener noreferrer'>{text}</a>"
                else:
                    text = f"<a href='{href_attr}'>{text}</a>"

            result.append(text)

        return ''.join(result)

    def _rich_text_to_plain_text(self, rich_texts: List[Dict[str, Any]]) -> str:
        """Extract plain text"""
        if not rich_texts:
            return ""

        return ''.join(rt.get('plain_text', '') for rt in rich_texts)

    def _escape_html(self, s: str) -> str:
        return (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
        )

    def _escape_html_attr(self, s: str) -> str:
        """Escape a string for safe use inside a single-quoted HTML attribute.

        Important: do NOT escape `<`, `>` or double quotes here. Hugo shortcodes
        (e.g. `{{< relref ... >}}`) can appear inside href attributes and must
        remain parseable by Hugo's shortcode engine.
        """
        return (s or "").replace("'", "&#39;")

    def _lookup_page_title(self, page_id: str) -> Optional[str]:
        """Return the title for a given Notion page id (compact or hyphenated)."""
        if not page_id:
            return None
        compact_id = page_id.replace('-', '')
        return self.id_to_title.get(page_id) or self.id_to_title.get(compact_id)

    def _extract_page_id_from_url(self, url: str) -> Optional[str]:
        """Extract a Notion page ID from a URL if present."""
        try:
            url_wo_fragment = url.split('#', 1)[0]
            patterns = [
                r"([0-9a-f]{32})$",
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
                r"([0-9a-f]{32})(?:\?.*)?$",
            ]
            for pat in patterns:
                m = re.search(pat, url_wo_fragment, re.IGNORECASE)
                if m:
                    return m.group(1)
        except Exception:
            return None
        return None

    def _rewrite_notion_link(self, url: str) -> str:
        """Rewrite Notion page links to local Hugo permalinks when possible.
        Supports URLs like https://www.notion.so/...-<id> or notion://... and raw IDs.
        """
        try:
            # Preserve URL fragment (e.g., #<block-id>) so anchor jumps still work
            from urllib.parse import urlparse
            parsed = urlparse(url)
            fragment = (parsed.fragment or '').strip()

            # If it's a pure same-page anchor, normalize Notion block id fragments
            if (url.startswith('#') or (not parsed.scheme and not parsed.netloc and not parsed.path)) and fragment:
                if re.fullmatch(r"[0-9a-fA-F\-]{36}", fragment) or re.fullmatch(r"[0-9a-fA-F]{32}", fragment):
                    return f"#{fragment.replace('-', '').lower()}"
                return f"#{fragment}"
            matched_id = self._extract_page_id_from_url(url)

            if matched_id and self.id_to_slug:
                slug = self.id_to_slug.get(matched_id) or self.id_to_slug.get(matched_id.replace('-', ''))
                if slug:
                    # Use Hugo relref so multilingual pages resolve to the current language
                    # (e.g., /en/... pages link to /en/... targets instead of falling back to zh).
                    slug_parts = self.normalize_slug_path(slug)
                    slug_base = slug_parts[-1] if slug_parts else slug.strip("/").strip()
                    slug_dir = "/".join(slug_parts[:-1]) if len(slug_parts) > 1 else ""
                    relref_path = f"{slug_dir}/{slug_base}.md" if slug_dir else f"{slug_base}.md"
                    relref = f'{{{{< relref path="{relref_path}" >}}}}'

                    # Append fragment if provided; normalize Notion-style uuids to compact lowercase
                    if fragment:
                        if re.fullmatch(r"[0-9a-fA-F\-]{36}", fragment) or re.fullmatch(r"[0-9a-fA-F]{32}", fragment):
                            norm_fragment = fragment.replace('-', '').lower()
                            return f"{relref}#{norm_fragment}"
                        return f"{relref}#{fragment}"
                    return relref
        except Exception:
            pass
        return url

    def _has_mermaid(self, blocks: List[Dict[str, Any]]) -> bool:
        """Detect if content contains Mermaid diagrams"""
        for block in blocks:
            block_type = block.get('type', '')
            if block_type == 'code':
                code_info = block.get('code', {})
                language = code_info.get('language', '').lower()
                if language == 'mermaid':
                    return True
                text = self._rich_text_to_plain_text(code_info.get('rich_text', []))
                if 'graph TD' in text or 'flowchart' in text or 'sequenceDiagram' in text:
                    return True
            # Search children as well
            if block.get('children'):
                if self._has_mermaid(block['children']):
                    return True
        return False

    def _has_math(self, blocks: List[Dict[str, Any]]) -> bool:
        """Check if contains mathematical formulas"""
        for block in blocks:
            if block.get('type') == 'equation':
                return True

            # Check inline formulas
            block_type = block.get('type', '')
            if block_type in ['paragraph', 'bulleted_list_item', 'numbered_list_item']:
                block_data = block.get(block_type, {})
                text_content = self._rich_text_to_plain_text(
                    block_data.get('rich_text', [])
                )
                if '$' in text_content or '\\\\(' in text_content or '\\\\[' in text_content:
                    return True

        return False

    def _extract_youtube_id(self, url: str) -> str:
        """Extract YouTube video ID"""
        patterns = [
            r'(?:youtube\\.com\\/watch\\?v=|youtu\\.be\\/)([^&\n?#]+)',
            r'youtube\\.com\\/embed\\/([^&\n?#]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        return ""

    def clean_posts_directory(self):
        """Clean generated Notion posts from content directory."""
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
        except Exception as e:
            logger.error(f"Error cleaning posts directory: {e}")

    def _has_notion_front_matter(self, path: Path) -> bool:
        try:
            with path.open('r', encoding='utf-8') as f:
                first_line = f.readline()
                if not first_line.startswith("---"):
                    return False
                fm_lines = []
                for line in f:
                    if line.startswith("---"):
                        break
                    fm_lines.append(line)
            front_matter = yaml.safe_load("".join(fm_lines)) or {}
            return bool(front_matter.get("notion_id"))
        except Exception:
            return False
