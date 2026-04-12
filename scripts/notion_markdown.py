import logging
import re
from html import unescape
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class NotionMarkdownAdapter:
    _TAG_NAMES = (
        "callout",
        "columns",
        "column",
        "details",
        "file",
        "video",
        "audio",
        "pdf",
        "page",
        "database",
        "synced_block",
        "meeting-notes",
    )

    _COLOR_MAP = {
        "default": "",
        "gray": "#6b7280",
        "brown": "#92400e",
        "orange": "#c2410c",
        "yellow": "#a16207",
        "green": "#15803d",
        "blue": "#2563eb",
        "purple": "#7c3aed",
        "pink": "#db2777",
        "red": "#dc2626",
        "gray_background": "rgba(107, 114, 128, 0.15)",
        "brown_background": "rgba(146, 64, 14, 0.12)",
        "orange_background": "rgba(194, 65, 12, 0.12)",
        "yellow_background": "rgba(161, 98, 7, 0.12)",
        "green_background": "rgba(21, 128, 61, 0.12)",
        "blue_background": "rgba(37, 99, 235, 0.12)",
        "purple_background": "rgba(124, 58, 237, 0.12)",
        "pink_background": "rgba(219, 39, 119, 0.12)",
        "red_background": "rgba(220, 38, 38, 0.12)",
    }

    def __init__(self, media_handler):
        self.media_handler = media_handler
        self.id_to_slug: Dict[str, str] = {}
        self.id_to_title: Dict[str, str] = {}

    def set_id_to_slug_mapping(
        self,
        mapping: Dict[str, str],
        title_mapping: Optional[Dict[str, str]] = None,
    ):
        self.id_to_slug = mapping or {}
        self.id_to_title = title_mapping or {}

    def convert(self, markdown: str, *, page_title: str = "") -> str:
        text = (markdown or "").replace("\r\n", "\n").replace("\r", "\n")
        text = self._strip_title_heading(text, page_title)
        lines = text.split("\n")
        converted = self._parse_lines(lines)
        return "\n".join(self._trim_blank_lines(converted)).strip()

    def _parse_lines(self, lines: list[str]) -> list[str]:
        out: list[str] = []
        index = 0

        while index < len(lines):
            line = lines[index]
            stripped = line.lstrip("\t")

            if stripped == "<empty-block/>":
                out.append("")
                index += 1
                continue

            if stripped.startswith("<table_of_contents"):
                out.append("{{< toc >}}")
                index += 1
                continue

            if self._is_open_tag(stripped, "callout"):
                raw_inner, index = self._collect_tag_block(lines, index + 1, "callout")
                inner_lines = self._parse_lines(self._dedent_lines(raw_inner))
                out.extend(self._render_callout(stripped, inner_lines))
                continue

            if self._is_open_tag(stripped, "columns"):
                raw_inner, index = self._collect_tag_block(lines, index + 1, "columns")
                out.extend(self._render_columns(raw_inner))
                continue

            if self._is_open_tag(stripped, "synced_block") or self._is_open_tag(stripped, "meeting-notes"):
                tag_name = "synced_block" if "synced_block" in stripped else "meeting-notes"
                raw_inner, index = self._collect_tag_block(lines, index + 1, tag_name)
                out.extend(self._parse_lines(self._dedent_lines(raw_inner)))
                continue

            if self._is_toggle_heading(line):
                raw_inner, index = self._collect_indented_block(lines, index + 1, self._leading_tabs(line))
                inner_lines = self._parse_lines(self._dedent_lines(raw_inner))
                out.extend(self._render_toggle(line, inner_lines))
                continue

            out.append(self._transform_plain_line(line))
            index += 1

        return out

    def _collect_tag_block(self, lines: list[str], start: int, tag_name: str) -> tuple[list[str], int]:
        depth = 1
        collected: list[str] = []
        index = start

        while index < len(lines):
            line = lines[index]
            stripped = line.lstrip("\t")

            if self._is_open_tag(stripped, tag_name):
                depth += 1
                collected.append(line)
                index += 1
                continue

            if stripped == f"</{tag_name}>":
                depth -= 1
                if depth == 0:
                    return collected, index + 1
                collected.append(line)
                index += 1
                continue

            collected.append(line)
            index += 1

        logger.warning("Unclosed Notion markdown tag <%s>; keeping collected content", tag_name)
        return collected, index

    def _collect_indented_block(
        self,
        lines: list[str],
        start: int,
        base_indent: int,
    ) -> tuple[list[str], int]:
        collected: list[str] = []
        index = start

        while index < len(lines):
            line = lines[index]
            if line.strip() and self._leading_tabs(line) <= base_indent:
                break
            collected.append(line)
            index += 1

        return collected, index

    def _render_callout(self, open_tag: str, inner_lines: list[str]) -> list[str]:
        icon = self._extract_attr(open_tag, "icon") or "💡"
        body = self._trim_blank_lines(inner_lines)
        if not body:
            return [f"> {icon}"]

        out: list[str] = []
        for idx, line in enumerate(body):
            if idx == 0 and line.strip():
                out.append(f"> {icon} {line}")
            elif idx == 0:
                out.append(f"> {icon}")
            elif line:
                out.append(f"> {line}")
            else:
                out.append(">")
        return out

    def _render_columns(self, lines: list[str]) -> list[str]:
        columns: list[str] = []
        index = 0

        while index < len(lines):
            line = lines[index]
            stripped = line.lstrip("\t")

            if self._is_open_tag(stripped, "column"):
                raw_inner, index = self._collect_tag_block(lines, index + 1, "column")
                inner_lines = self._parse_lines(self._dedent_lines(raw_inner))
                column_text = "\n".join(self._trim_blank_lines(inner_lines)).strip()
                if column_text:
                    columns.append(column_text)
                continue

            transformed = self._transform_plain_line(self._dedent_line(line))
            if transformed.strip():
                columns.append(transformed.strip())
            index += 1

        if not columns:
            return []

        out: list[str] = []
        for idx, column in enumerate(columns):
            if idx > 0:
                out.extend(["", ""])
            out.extend(column.splitlines())
        return out

    def _render_toggle(self, line: str, inner_lines: list[str]) -> list[str]:
        title = self._strip_notion_block_attributes(line.lstrip("\t"))
        title = re.sub(r"^#{1,6}\s+", "", title).strip()
        if not title:
            title = "Details"

        out = ["<details>", f"<summary>{self._transform_inline_text(title)}</summary>", ""]
        out.extend(inner_lines)
        out.extend(["", "</details>"])
        return out

    def _transform_plain_line(self, line: str) -> str:
        leading = re.match(r"^[\t ]*", line).group(0)
        body = line[len(leading):]

        if not body:
            return ""

        body = self._strip_notion_block_attributes(body)
        body = self._replace_inline_spans(body)
        body = self._replace_media_tags(body)
        body = self._replace_reference_tags(body)
        body = self._replace_mention_tags(body)
        body = self._replace_images(body)
        body = self._replace_markdown_links(body)
        body = self._replace_unknown_tags(body)
        body = body.replace("<empty-block/>", "")

        if body.startswith("<table_of_contents"):
            return "{{< toc >}}"

        return f"{leading}{body}"

    def _replace_media_tags(self, text: str) -> str:
        pattern = re.compile(
            r"<(?P<tag>file|video|audio|pdf)\s+(?P<attrs>[^>]*?)(?:\s*/>|>(?P<body>.*?)</(?P=tag)>)",
            re.DOTALL,
        )

        def repl(match: re.Match[str]) -> str:
            tag = match.group("tag")
            attrs = match.group("attrs") or ""
            caption = (match.group("body") or "").strip()
            url = self._extract_attr(attrs, "src") or ""
            return self._render_media_tag(tag, url, caption)

        return pattern.sub(repl, text)

    def _replace_reference_tags(self, text: str) -> str:
        pattern = re.compile(
            r"<(?P<tag>page|database)\s+(?P<attrs>[^>]*?)(?:\s*/>|>(?P<body>.*?)</(?P=tag)>)",
            re.DOTALL,
        )

        def repl(match: re.Match[str]) -> str:
            attrs = match.group("attrs") or ""
            label = (match.group("body") or "").strip()
            url = self._extract_attr(attrs, "url") or ""
            rewritten = self._rewrite_notion_link(url)
            resolved_title = self._lookup_page_title_from_url(url)
            text_value = self._transform_inline_text(label or resolved_title or url)
            if not rewritten:
                return text_value
            return f"[{text_value}]({rewritten})"

        return pattern.sub(repl, text)

    def _replace_mention_tags(self, text: str) -> str:
        pattern = re.compile(
            r"<(?P<tag>mention-page|mention-database|mention-data-source|mention-user|mention-agent|mention-date)\s+"
            r"(?P<attrs>[^>]*?)(?:\s*/>|>(?P<body>.*?)</(?P=tag)>)",
            re.DOTALL,
        )

        def repl(match: re.Match[str]) -> str:
            tag = match.group("tag")
            attrs = match.group("attrs") or ""
            body = (match.group("body") or "").strip()

            if tag in {"mention-page", "mention-database", "mention-data-source"}:
                url = self._extract_attr(attrs, "url") or ""
                label = body or self._lookup_page_title_from_url(url) or url
                rewritten = self._rewrite_notion_link(url)
                label = self._transform_inline_text(label)
                return f"[{label}]({rewritten})" if rewritten else label

            if tag == "mention-date":
                start = self._extract_attr(attrs, "start") or self._extract_attr(attrs, "date") or body
                end = self._extract_attr(attrs, "end") or ""
                if start and end:
                    return f"{start} -> {end}"
                return start

            return self._transform_inline_text(body)

        return pattern.sub(repl, text)

    def _replace_unknown_tags(self, text: str) -> str:
        pattern = re.compile(r"<unknown\s+([^>/]*?)\s*/>")

        def repl(match: re.Match[str]) -> str:
            attrs = match.group(1) or ""
            url = self._extract_attr(attrs, "url") or ""
            alt = self._extract_attr(attrs, "alt") or "unknown"
            if url:
                return f"[Unsupported Notion block: {alt}]({url})"
            return f"Unsupported Notion block: {alt}"

        return pattern.sub(repl, text)

    def _replace_images(self, text: str) -> str:
        pattern = re.compile(r"!\[(?P<alt>.*?)\]\((?P<url>[^)]+)\)")

        def repl(match: re.Match[str]) -> str:
            alt = match.group("alt") or ""
            url = (match.group("url") or "").strip()
            local_path = self.media_handler.download_media(url, "image")
            return f"![{alt}]({local_path})"

        return pattern.sub(repl, text)

    def _replace_markdown_links(self, text: str) -> str:
        pattern = re.compile(r"(?<!!)\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)")

        def repl(match: re.Match[str]) -> str:
            label = match.group("label")
            target = (match.group("target") or "").strip()
            url = target
            title = ""
            title_match = re.match(r'^(?P<url>\S+)(?P<title>\s+".*")$', target)
            if title_match:
                url = title_match.group("url")
                title = title_match.group("title")

            rewritten = self._rewrite_notion_link(url)
            return f"[{label}]({rewritten}{title})"

        return pattern.sub(repl, text)

    def _replace_inline_spans(self, text: str) -> str:
        pattern = re.compile(r"<span\s+([^>]*?)>(.*?)</span>", re.DOTALL)

        def repl(match: re.Match[str]) -> str:
            attrs = match.group(1) or ""
            body = match.group(2) or ""
            color = self._extract_attr(attrs, "color") or ""
            underline = (self._extract_attr(attrs, "underline") or "").lower() == "true"

            transformed = body
            if underline:
                transformed = f"<u>{transformed}</u>"

            style_parts: list[str] = []
            css_color = self._COLOR_MAP.get(color, "")
            if css_color:
                style_key = "background" if color.endswith("_background") else "color"
                style_parts.append(f"{style_key}: {css_color}")

            if not style_parts:
                return transformed

            return f"<span style=\"{'; '.join(style_parts)}\">{transformed}</span>"

        return pattern.sub(repl, text)

    def _render_media_tag(self, tag: str, url: str, caption: str) -> str:
        if not url:
            return caption

        plain_caption = self._transform_inline_text(caption) if caption else ""
        if tag == "file":
            local_path = self.media_handler.download_media(url, "file")
            label = plain_caption or "Download file"
            return f"📎 [{label}]({local_path})"

        if tag == "pdf":
            local_path = self.media_handler.download_media(url, "pdf")
            label = plain_caption or "PDF"
            return f"📄 [{label}]({local_path})"

        if tag == "audio":
            local_path = self.media_handler.download_media(url, "audio")
            figcaption = f"\n  <figcaption>{plain_caption}</figcaption>" if plain_caption else ""
            return (
                "<figure>\n"
                "  <audio controls preload=\"none\" style=\"width: 100%;\">\n"
                f"    <source src=\"{local_path}\">\n"
                "  </audio>"
                f"{figcaption}\n"
                "</figure>"
            )

        if tag == "video":
            local_path = self.media_handler.download_media(url, "video")
            figcaption = f"\n  <figcaption>{plain_caption}</figcaption>" if plain_caption else ""
            return (
                "<figure>\n"
                "  <video controls style=\"width: 100%; max-width: 100%; display: block; margin: 1.5rem 0;\">\n"
                f"    <source src=\"{local_path}\">\n"
                "  </video>"
                f"{figcaption}\n"
                "</figure>"
            )

        return caption

    def _strip_title_heading(self, text: str, page_title: str) -> str:
        if not text.strip() or not page_title.strip():
            return text

        lines = text.split("\n")
        first_non_empty = next((idx for idx, line in enumerate(lines) if line.strip()), None)
        if first_non_empty is None:
            return text

        line = self._strip_notion_block_attributes(lines[first_non_empty].strip())
        match = re.match(r"^#\s+(.*)$", line)
        if not match:
            return text

        heading = self._normalize_compare_text(match.group(1))
        title = self._normalize_compare_text(page_title)
        if heading != title:
            return text

        del lines[first_non_empty]
        if first_non_empty < len(lines) and not lines[first_non_empty].strip():
            del lines[first_non_empty]
        return "\n".join(lines)

    def _strip_notion_block_attributes(self, text: str) -> str:
        return re.sub(r'\s+\{[a-zA-Z0-9_\-]+="[^"]*"(?:\s+[a-zA-Z0-9_\-]+="[^"]*")*\}\s*$', "", text)

    def _normalize_compare_text(self, value: str) -> str:
        normalized = unescape(value or "")
        normalized = self._strip_notion_block_attributes(normalized)
        normalized = re.sub(r"<[^>]+>", "", normalized)
        return " ".join(normalized.strip().split()).lower()

    def _extract_attr(self, text: str, name: str) -> str:
        match = re.search(rf'{re.escape(name)}="([^"]*)"', text or "")
        return unescape(match.group(1)) if match else ""

    def _is_open_tag(self, line: str, tag_name: str) -> bool:
        return bool(re.match(rf"^<{re.escape(tag_name)}(?:\s+[^>]*)?>$", line.strip()))

    def _is_toggle_heading(self, line: str) -> bool:
        stripped = line.lstrip("\t")
        if not re.match(r"^#{1,4}\s+", stripped):
            return False
        return 'toggle="true"' in stripped

    def _leading_tabs(self, line: str) -> int:
        count = 0
        for char in line:
            if char == "\t":
                count += 1
                continue
            break
        return count

    def _dedent_lines(self, lines: list[str], levels: int = 1) -> list[str]:
        return [self._dedent_line(line, levels=levels) for line in lines]

    def _dedent_line(self, line: str, levels: int = 1) -> str:
        out = line
        for _ in range(levels):
            if out.startswith("\t"):
                out = out[1:]
            elif out.startswith("    "):
                out = out[4:]
        return out

    def _trim_blank_lines(self, lines: list[str]) -> list[str]:
        start = 0
        end = len(lines)

        while start < end and not lines[start].strip():
            start += 1
        while end > start and not lines[end - 1].strip():
            end -= 1

        return lines[start:end]

    def _transform_inline_text(self, text: str) -> str:
        transformed = text or ""
        transformed = self._replace_inline_spans(transformed)
        transformed = self._replace_reference_tags(transformed)
        transformed = self._replace_mention_tags(transformed)
        transformed = self._replace_markdown_links(transformed)
        return transformed

    def _lookup_page_title_from_url(self, url: str) -> Optional[str]:
        page_id = self._extract_page_id_from_url(url)
        if not page_id:
            return None
        compact_id = page_id.replace("-", "")
        return self.id_to_title.get(page_id) or self.id_to_title.get(compact_id)

    def _extract_page_id_from_url(self, url: str) -> Optional[str]:
        try:
            url_wo_fragment = (url or "").split("#", 1)[0]
            patterns = [
                r"([0-9a-f]{32})$",
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
                r"([0-9a-f]{32})(?:\?.*)?$",
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\?.*)?$",
            ]
            for pattern in patterns:
                match = re.search(pattern, url_wo_fragment, re.IGNORECASE)
                if match:
                    return match.group(1)
        except Exception:
            return None
        return None

    def _rewrite_notion_link(self, url: str) -> str:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url or "")
            fragment = (parsed.fragment or "").strip()

            if (url.startswith("#") or (not parsed.scheme and not parsed.netloc and not parsed.path)) and fragment:
                normalized = fragment.replace("-", "").lower()
                return f"#{normalized}"

            matched_id = self._extract_page_id_from_url(url)
            if matched_id and self.id_to_slug:
                slug = self.id_to_slug.get(matched_id) or self.id_to_slug.get(matched_id.replace("-", ""))
                if slug:
                    slug_parts = [part for part in slug.strip("/").split("/") if part]
                    slug_base = slug_parts[-1] if slug_parts else slug.strip("/").strip()
                    slug_dir = "/".join(slug_parts[:-1]) if len(slug_parts) > 1 else ""
                    relref_path = f"{slug_dir}/{slug_base}.md" if slug_dir else f"{slug_base}.md"
                    relref = f'{{{{< relref path="{relref_path}" >}}}}'
                    if fragment:
                        normalized = fragment.replace("-", "").lower()
                        return f"{relref}#{normalized}"
                    return relref
        except Exception:
            return url
        return url
