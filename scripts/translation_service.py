import hashlib
import logging
import os
import re
import time
from functools import lru_cache
from datetime import datetime
from typing import Optional

import requests
import tiktoken

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_MODEL = "google/gemma-4-31b-it:free"
DEFAULT_OPENROUTER_SITE_URL = "https://github.com/binbinsh/notion-autoblog"
DEFAULT_OPENROUTER_APP_NAME = "notion-autoblog"
DEFAULT_LOG_PREVIEW_CHARS = 160
DEFAULT_CONTEXT_WINDOW_SIZE = 131_072
DEFAULT_TIKTOKEN_ENCODING = "o200k_harmony"
DEFAULT_TRANSLATION_OUTPUT_TOKEN_MULTIPLIER = 1.25
DEFAULT_TRANSLATION_OUTPUT_TOKEN_MARGIN = 512
DEFAULT_TRANSLATION_TOKEN_SAFETY_MARGIN = 2048
DEFAULT_TRANSLATION_MIN_CHUNK_TOKENS = 500  # larger chunks-> worse quality
DEFAULT_TRANSLATION_MAX_SPLIT_DEPTH = 8
DEFAULT_TRANSLATION_VERIFICATION_ENABLED = True
DEFAULT_TRANSLATION_MAX_REWORK_ATTEMPTS = 2

# Language detection patterns for various scripts
# Each pattern detects characters specific to a language/script
_LANGUAGE_PATTERNS = {
    # East Asian languages
    "zh": re.compile(r'[\u4e00-\u9fff]'),  # Chinese (CJK Unified Ideographs)
    "ja": re.compile(r'[\u3040-\u309f\u30a0-\u30ff]'),  # Japanese (Hiragana + Katakana)
    "ko": re.compile(r'[\uac00-\ud7af\u1100-\u11ff]'),  # Korean (Hangul)
    # Cyrillic languages (Russian, Ukrainian, Bulgarian, etc.)
    "ru": re.compile(r'[\u0400-\u04ff]'),  # Cyrillic
    # Middle Eastern languages
    "ar": re.compile(r'[\u0600-\u06ff]'),  # Arabic
    "he": re.compile(r'[\u0590-\u05ff]'),  # Hebrew
    "fa": re.compile(r'[\u0600-\u06ff\u0750-\u077f]'),  # Persian (Arabic + Extended)
    # South Asian languages
    "hi": re.compile(r'[\u0900-\u097f]'),  # Hindi (Devanagari)
    "th": re.compile(r'[\u0e00-\u0e7f]'),  # Thai
    "vi": re.compile(r'[\u1e00-\u1eff]'),  # Vietnamese (Latin Extended)
    # Greek
    "el": re.compile(r'[\u0370-\u03ff]'),  # Greek
}

# Language name mappings for better prompts
_LANGUAGE_NAMES = {
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
    "chinese": "Chinese",
    "中文": "Chinese",
    "ja": "Japanese",
    "japanese": "Japanese",
    "日本語": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
    "한국어": "Korean",
    "ru": "Russian",
    "russian": "Russian",
    "русский": "Russian",
    "ar": "Arabic",
    "arabic": "Arabic",
    "العربية": "Arabic",
    "he": "Hebrew",
    "hebrew": "Hebrew",
    "fa": "Persian",
    "persian": "Persian",
    "hi": "Hindi",
    "hindi": "Hindi",
    "th": "Thai",
    "thai": "Thai",
    "vi": "Vietnamese",
    "vietnamese": "Vietnamese",
    "el": "Greek",
    "greek": "Greek",
    "en": "English",
    "english": "English",
    "de": "German",
    "german": "German",
    "fr": "French",
    "french": "French",
    "es": "Spanish",
    "spanish": "Spanish",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "it": "Italian",
    "italian": "Italian",
}


def _normalize_language(lang: str) -> str:
    """Normalize language code to standard form."""
    lang_lower = (lang or "").strip().lower()
    return _LANGUAGE_NAMES.get(lang_lower, lang)


def _get_language_pattern(lang: str) -> re.Pattern | None:
    """Get the character pattern for a language."""
    lang_lower = (lang or "").strip().lower()
    # Direct match
    if lang_lower in _LANGUAGE_PATTERNS:
        return _LANGUAGE_PATTERNS[lang_lower]
    # Try normalized name
    for key, pattern in _LANGUAGE_PATTERNS.items():
        if _LANGUAGE_NAMES.get(key, "").lower() == _normalize_language(lang_lower).lower():
            return pattern
    # Special mappings
    if lang_lower in ("zh-cn", "zh-tw", "chinese", "中文"):
        return _LANGUAGE_PATTERNS["zh"]
    if lang_lower in ("japanese", "日本語"):
        return _LANGUAGE_PATTERNS["ja"]
    if lang_lower in ("korean", "한국어"):
        return _LANGUAGE_PATTERNS["ko"]
    if lang_lower in ("russian", "русский"):
        return _LANGUAGE_PATTERNS["ru"]
    if lang_lower in ("arabic", "العربية"):
        return _LANGUAGE_PATTERNS["ar"]
    return None


def _contains_language_chars(text: str, lang: str) -> bool:
    """Check if text contains characters from the specified language."""
    if not text:
        return False
    pattern = _get_language_pattern(lang)
    if not pattern:
        return False
    return bool(pattern.search(text))


def _extract_language_segments(text: str, lang: str) -> list[str]:
    """Extract segments containing characters from the specified language."""
    if not text:
        return []
    pattern = _get_language_pattern(lang)
    if not pattern:
        return []
    # Build a pattern to find sequences of the language's characters
    base_pattern = pattern.pattern.strip('[]')
    segment_pattern = re.compile(f'[{base_pattern}]+(?:[^{base_pattern}]{{0,10}}[{base_pattern}]+)*')
    return segment_pattern.findall(text)


def _translation_verification_enabled() -> bool:
    """Check if translation verification is enabled."""
    raw = (os.getenv("TRANSLATION_VERIFICATION_ENABLED") or "").strip().lower()
    if not raw:
        return DEFAULT_TRANSLATION_VERIFICATION_ENABLED
    return raw in ("1", "true", "yes", "on")


def _translation_max_rework_attempts() -> int:
    """Max number of rework attempts for translation verification."""
    raw = (os.getenv("TRANSLATION_MAX_REWORK_ATTEMPTS") or "").strip()
    if not raw:
        return DEFAULT_TRANSLATION_MAX_REWORK_ATTEMPTS
    try:
        value = int(raw)
        return max(0, min(value, 5))
    except Exception:
        return DEFAULT_TRANSLATION_MAX_REWORK_ATTEMPTS


def _collapse_whitespace(text: str) -> str:
    """Collapse whitespace for compact, single-line log previews."""
    return " ".join((text or "").split())


def _preview(text: str, limit: int) -> str:
    """Return a short, single-line preview for logs."""
    cleaned = _collapse_whitespace(text)
    if not cleaned:
        return ""
    if limit <= 0:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}…"


def _log_preview_chars() -> int:
    """Read preview length from env var for translation request/response logs."""
    raw = (os.getenv("TRANSLATION_LOG_PREVIEW_CHARS") or "").strip()
    if not raw:
        return DEFAULT_LOG_PREVIEW_CHARS
    try:
        value = int(raw)
        return max(0, min(value, 2000))
    except Exception:
        return DEFAULT_LOG_PREVIEW_CHARS


def _context_window_size_tokens() -> int:
    """Read model context window size (tokens) from env var.

    This is a model limit (not an OpenRouter limit) and is used to plan chunk sizes
    before calling the model.
    """
    raw = (os.getenv("CONTEXT_WINDOW_SIZE") or "").strip()
    if not raw:
        return DEFAULT_CONTEXT_WINDOW_SIZE
    try:
        value = int(raw)
        if value <= 0:
            return DEFAULT_CONTEXT_WINDOW_SIZE
        return min(value, 2_000_000)
    except Exception:
        return DEFAULT_CONTEXT_WINDOW_SIZE


def _translation_output_token_multiplier() -> float:
    """Expected output tokens per input token for translation."""
    raw = (os.getenv("TRANSLATION_OUTPUT_TOKEN_MULTIPLIER") or "").strip()
    if not raw:
        return DEFAULT_TRANSLATION_OUTPUT_TOKEN_MULTIPLIER
    try:
        value = float(raw)
        if value <= 0:
            return DEFAULT_TRANSLATION_OUTPUT_TOKEN_MULTIPLIER
        return min(value, 10.0)
    except Exception:
        return DEFAULT_TRANSLATION_OUTPUT_TOKEN_MULTIPLIER


def _translation_output_token_margin() -> int:
    """Extra output token margin reserved for non-content overhead."""
    raw = (os.getenv("TRANSLATION_OUTPUT_TOKEN_MARGIN") or "").strip()
    if not raw:
        return DEFAULT_TRANSLATION_OUTPUT_TOKEN_MARGIN
    try:
        value = int(raw)
        if value < 0:
            return DEFAULT_TRANSLATION_OUTPUT_TOKEN_MARGIN
        return min(value, 200_000)
    except Exception:
        return DEFAULT_TRANSLATION_OUTPUT_TOKEN_MARGIN


def _translation_token_safety_margin() -> int:
    """Reserve tokens to avoid hitting the hard context window."""
    raw = (os.getenv("TRANSLATION_TOKEN_SAFETY_MARGIN") or "").strip()
    if not raw:
        return DEFAULT_TRANSLATION_TOKEN_SAFETY_MARGIN
    try:
        value = int(raw)
        if value < 0:
            return DEFAULT_TRANSLATION_TOKEN_SAFETY_MARGIN
        return min(value, 200_000)
    except Exception:
        return DEFAULT_TRANSLATION_TOKEN_SAFETY_MARGIN


def _translation_min_chunk_tokens() -> int:
    """Read the minimum chunk size before giving up splitting further."""
    raw = (os.getenv("TRANSLATION_MIN_CHUNK_TOKENS") or "").strip()
    if not raw:
        return DEFAULT_TRANSLATION_MIN_CHUNK_TOKENS
    try:
        value = int(raw)
        if value <= 0:
            return DEFAULT_TRANSLATION_MIN_CHUNK_TOKENS
        return min(value, 50_000)
    except Exception:
        return DEFAULT_TRANSLATION_MIN_CHUNK_TOKENS


def _translation_max_split_depth() -> int:
    """Read max recursive split depth (only used when provider truncates)."""
    raw = (os.getenv("TRANSLATION_MAX_SPLIT_DEPTH") or "").strip()
    if not raw:
        return DEFAULT_TRANSLATION_MAX_SPLIT_DEPTH
    try:
        value = int(raw)
        if value <= 0:
            return DEFAULT_TRANSLATION_MAX_SPLIT_DEPTH
        return min(value, 32)
    except Exception:
        return DEFAULT_TRANSLATION_MAX_SPLIT_DEPTH


def _openrouter_max_tokens() -> Optional[int]:
    """Read max_tokens from env var for OpenRouter requests.

    If unset/invalid, returns None and lets the provider decide.
    """
    raw = (os.getenv("OPENROUTER_MAX_TOKENS") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
        if value <= 0:
            return None
        return min(value, 200_000)
    except Exception:
        return None


def _tiktoken_encoding_name() -> str:
    name = (os.getenv("TIKTOKEN_ENCODING") or DEFAULT_TIKTOKEN_ENCODING).strip()
    return name or DEFAULT_TIKTOKEN_ENCODING

@lru_cache(maxsize=1)
def _get_tiktoken_encoding():
    name = _tiktoken_encoding_name()
    return tiktoken.get_encoding(name)


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken for deterministic chunk planning."""
    if not text:
        return 0
    enc = _get_tiktoken_encoding()
    return len(enc.encode(text))


def _count_request_tokens(system_prompt: str, user_prompt: str) -> int:
    """Approximate tokens for a chat-completions request (system+user)."""
    enc = _get_tiktoken_encoding()
    messages = [
        {"role": "system", "content": system_prompt or ""},
        {"role": "user", "content": user_prompt or ""},
    ]

    # Best-effort constants (OpenAI ChatML-style accounting).
    tokens_per_message = 3
    tokens_per_name = 1

    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            if value:
                num_tokens += len(enc.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed
    return num_tokens


def _compute_user_chunk_budget_tokens(system_prompt: str) -> int:
    """Compute max user content tokens per request based on context window planning."""
    context_window = _context_window_size_tokens()
    safety_margin = _translation_token_safety_margin()
    output_multiplier = _translation_output_token_multiplier()
    output_margin = _translation_output_token_margin()

    base_tokens = _count_request_tokens(system_prompt or "", "")
    available = context_window - safety_margin - output_margin - base_tokens
    if available <= 0:
        return 0
    budget = int(available / (1.0 + output_multiplier))
    return max(1, budget)


_FENCE_RE = re.compile(r"^\s*(```+|~~~+)(.*)$")


class _MarkdownBlock:
    __slots__ = ("kind", "text", "lang")

    def __init__(self, kind: str, text: str, lang: Optional[str] = None):
        self.kind = kind  # "text" | "fence"
        self.text = text
        self.lang = lang


def _parse_markdown_fences(markdown: str) -> list[_MarkdownBlock]:
    """Split Markdown into blocks, keeping fenced code blocks intact."""
    if not markdown:
        return []

    lines = markdown.splitlines(keepends=True)
    blocks: list[_MarkdownBlock] = []
    buf: list[str] = []

    in_fence = False
    fence_delim = ""
    fence_lang: Optional[str] = None

    def flush_text():
        nonlocal buf
        if buf:
            blocks.append(_MarkdownBlock("text", "".join(buf)))
            buf = []

    for line in lines:
        m = _FENCE_RE.match(line)
        if not m:
            buf.append(line)
            continue

        delim = (m.group(1) or "").strip()
        tail = (m.group(2) or "").strip()

        if not in_fence:
            flush_text()
            in_fence = True
            fence_delim = delim
            fence_lang = (tail.split()[0].strip().lower() if tail else None) or None
            buf.append(line)
            continue

        # Closing fence: same marker type and at least as long as opening fence.
        if delim and fence_delim and delim[0] == fence_delim[0] and len(delim) >= len(fence_delim):
            buf.append(line)
            blocks.append(_MarkdownBlock("fence", "".join(buf), lang=fence_lang))
            buf = []
            in_fence = False
            fence_delim = ""
            fence_lang = None
            continue

        # A fence-like line inside a fence; treat as normal content.
        buf.append(line)

    # Flush remaining buffer
    if buf:
        kind = "fence" if in_fence else "text"
        blocks.append(_MarkdownBlock(kind, "".join(buf), lang=fence_lang))

    return blocks


def _split_plain_text_by_tokens(text: str, max_tokens: int) -> list[str]:
    """Split plain text (no fenced blocks) into chunks within token budget."""
    if not text:
        return []
    if max_tokens <= 0:
        return [text]

    if _count_tokens(text) <= max_tokens:
        return [text]

    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    safe_split_idx: Optional[int] = None

    def flush(count: int):
        nonlocal cur, cur_tokens, safe_split_idx
        if count <= 0:
            return
        chunks.append("".join(cur[:count]))
        cur = cur[count:]
        cur_tokens = sum(_count_tokens(x) for x in cur)
        safe_split_idx = None
        # Recompute safe split point within remaining buffer (blank line boundary)
        for i, ln in enumerate(cur, start=1):
            if ln.strip() == "":
                safe_split_idx = i

    for line in lines:
        line_tokens = _count_tokens(line)
        # If a single line is too large, hard-split it by token budget.
        if line_tokens > max_tokens and not cur:
            remaining = line
            while remaining:
                if _count_tokens(remaining) <= max_tokens:
                    chunks.append(remaining)
                    remaining = ""
                    break
                # Binary search for the largest prefix under budget.
                lo, hi = 1, len(remaining)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if _count_tokens(remaining[:mid]) <= max_tokens:
                        lo = mid + 1
                    else:
                        hi = mid
                cut = max(1, lo - 1)
                chunks.append(remaining[:cut])
                remaining = remaining[cut:]
            continue

        # Ensure the current chunk stays within budget, splitting at the last blank line when possible.
        while cur and cur_tokens + line_tokens > max_tokens:
            split_at = safe_split_idx or len(cur)
            if split_at <= 0:
                split_at = len(cur)
            flush(split_at)

        cur.append(line)
        cur_tokens += line_tokens
        if line.strip() == "":
            safe_split_idx = len(cur)

    if cur:
        chunks.append("".join(cur))
    return chunks


def _split_markdown_translatable(text: str, max_tokens: int) -> list[str]:
    """Split Markdown into chunks within token budget, keeping fences intact."""
    if not text:
        return []
    if max_tokens <= 0:
        return [text]

    blocks = _parse_markdown_fences(text)
    chunks: list[str] = []
    cur_parts: list[str] = []
    cur_tokens = 0

    def flush():
        nonlocal cur_parts, cur_tokens
        if cur_parts:
            chunks.append("".join(cur_parts))
            cur_parts = []
            cur_tokens = 0

    for blk in blocks:
        blk_tokens = _count_tokens(blk.text)
        if blk.kind == "text" and blk_tokens > max_tokens:
            flush()
            chunks.extend(_split_plain_text_by_tokens(blk.text, max_tokens))
            continue

        if cur_parts and cur_tokens + blk_tokens > max_tokens:
            flush()

        cur_parts.append(blk.text)
        cur_tokens += blk_tokens

    flush()
    return chunks


def _preserve_trailing_newlines(original: str, translated: str) -> str:
    """Preserve the number of trailing newlines from the original chunk."""
    if not original:
        return translated
    trailing = len(original) - len(original.rstrip("\n"))
    if trailing <= 0:
        return translated
    return translated.rstrip("\n") + ("\n" * trailing)


class OpenRouterTranslator:
    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        cache_manager=None,
        site_url: Optional[str] = DEFAULT_OPENROUTER_SITE_URL,
        app_name: Optional[str] = DEFAULT_OPENROUTER_APP_NAME,
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.model = (model or os.getenv("OPENROUTER_TRANSLATION_MODEL") or DEFAULT_OPENROUTER_MODEL).strip()
        self.cache_manager = cache_manager
        self.site_url = site_url
        self.app_name = app_name
        self.timeout = timeout
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        logger.info(
            "OpenRouter translator enabled (model=%s, timeout=%ss, cache=%s)",
            self.model,
            self.timeout,
            "on" if bool(self.cache_manager) else "off",
        )

    def translate(self, source_lang: str, target_lang: str, title: str, content: str) -> Optional[dict[str, str]]:
        if not source_lang or not target_lang:
            return None

        title_cache_key = self._build_cache_key(source_lang, target_lang, field="title", text=title)
        content_cache_key = self._build_cache_key(source_lang, target_lang, field="content", text=content)

        cached_title = None
        cached_content = None
        if self.cache_manager:
            cached_title_payload = self.cache_manager.get_cached_translation(title_cache_key)
            if cached_title_payload:
                cached_title = cached_title_payload.get("text") or ""
            cached_content_payload = self.cache_manager.get_cached_translation(content_cache_key)
            if cached_content_payload:
                cached_content = cached_content_payload.get("text") or ""

        preview_chars = _log_preview_chars()
        title_preview = _preview(title, min(preview_chars, 120))
        logger.info(
            "Translation start: %s -> %s (model=%s, title_preview=%r, content_chars=%s)",
            source_lang,
            target_lang,
            self.model,
            title_preview,
            len(content or ""),
        )

        headers = self._build_headers()

        try:
            # 1) Title translation (single line). No fallback.
            translated_title = cached_title
            if cached_title:
                logger.info(
                    "Translation cache HIT: title (key=%s…, chars=%s)",
                    title_cache_key[:12],
                    len(cached_title),
                )
            else:
                logger.info("Translation cache MISS: title (key=%s…)", title_cache_key[:12])
            if not translated_title:
                translated_title = self._translate_title(
                    source_lang=source_lang,
                    target_lang=target_lang,
                    title=title,
                    headers=headers,
                )
                if self.cache_manager and translated_title:
                    self.cache_manager.cache_translation(
                        title_cache_key,
                        {
                            "field": "title",
                            "text": translated_title,
                            "source_lang": source_lang,
                            "target_lang": target_lang,
                            "model": self.model,
                            "created_at": datetime.now().isoformat(),
                        },
                    )
                    logger.info(
                        "Translation cache STORE: title (key=%s…, chars=%s)",
                        title_cache_key[:12],
                        len(translated_title),
                    )

            if not translated_title:
                logger.error("Translation title is empty for %s -> %s", source_lang, target_lang)
                return None

            # 2) Content translation (markdown). No fallback.
            translated_content = cached_content
            from_cache = bool(cached_content)
            if cached_content:
                logger.info(
                    "Translation cache HIT: content (key=%s…, chars=%s)",
                    content_cache_key[:12],
                    len(cached_content),
                )
            else:
                logger.info("Translation cache MISS: content (key=%s…)", content_cache_key[:12])
            if not translated_content:
                translated_content = self._translate_content(
                    source_lang=source_lang,
                    target_lang=target_lang,
                    content=content,
                    headers=headers,
                )
                if self.cache_manager and translated_content:
                    self.cache_manager.cache_translation(
                        content_cache_key,
                        {
                            "field": "content",
                            "text": translated_content,
                            "source_lang": source_lang,
                            "target_lang": target_lang,
                            "model": self.model,
                            "created_at": datetime.now().isoformat(),
                        },
                    )
                    logger.info(
                        "Translation cache STORE: content (key=%s…, chars=%s)",
                        content_cache_key[:12],
                        len(translated_content),
                    )

            # Verify cached translations too (they may have been incomplete)
            if from_cache and translated_content and _translation_verification_enabled():
                logger.info("Verifying cached translation: %s -> %s", source_lang, target_lang)
                is_complete, untranslated_segments = self._verify_translation_completeness(
                    source_lang=source_lang,
                    target_lang=target_lang,
                    original=content,
                    translated=translated_content,
                    headers=headers,
                )
                if not is_complete:
                    logger.warning(
                        "Cached translation incomplete, reworking: %s -> %s (untranslated=%d)",
                        source_lang,
                        target_lang,
                        len(untranslated_segments),
                    )
                    # Invalidate cache and re-translate with verification
                    translated_content = self._translate_content(
                        source_lang=source_lang,
                        target_lang=target_lang,
                        content=content,
                        headers=headers,
                    )
                    if self.cache_manager and translated_content:
                        self.cache_manager.cache_translation(
                            content_cache_key,
                            {
                                "field": "content",
                                "text": translated_content,
                                "source_lang": source_lang,
                                "target_lang": target_lang,
                                "model": self.model,
                                "created_at": datetime.now().isoformat(),
                            },
                        )
                        logger.info(
                            "Translation cache UPDATE: content (key=%s…, chars=%s)",
                            content_cache_key[:12],
                            len(translated_content),
                        )

            if not translated_content:
                logger.error("Translation content is empty for %s -> %s", source_lang, target_lang)
                return None

            logger.info(
                "Translation done: %s -> %s (model=%s, title_chars=%s, content_chars=%s)",
                source_lang,
                target_lang,
                self.model,
                len(translated_title),
                len(translated_content),
            )
            return {"title": translated_title, "content": translated_content}
        except Exception as e:
            logger.exception("Translation failed for %s -> %s: %s", source_lang, target_lang, e)
            return None

    def _build_cache_key(self, source_lang: str, target_lang: str, *, field: str, text: str) -> str:
        payload_text = f"{field}\n{text}"
        digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
        key = f"{self.model}:{source_lang}:{target_lang}:{field}:{digest}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name
        return headers

    def _call_openrouter(
        self,
        *,
        headers: dict[str, str],
        system_prompt: str,
        user_prompt: str,
        stop: Optional[list[str]] = None,
        max_tokens: Optional[int] = None,
        request_label: str,
        temperature: float = 0.2,
        force_max_tokens: bool = False,
    ) -> tuple[str, str, dict]:
        preview_chars = _log_preview_chars()
        configured_max_tokens = _openrouter_max_tokens()
        if configured_max_tokens is None:
            # Only set max_tokens when explicitly configured. Different models/providers
            # have different completion limits; relying on the provider default avoids
            # sending an invalid max_tokens value.
            if not force_max_tokens:
                max_tokens = None
        else:
            if max_tokens is None:
                max_tokens = configured_max_tokens
            else:
                max_tokens = min(max_tokens, configured_max_tokens)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if stop:
            body["stop"] = stop
        logger.info(
            "OpenRouter request: %s (model=%s, max_tokens=%s, user_chars=%s, user_preview=%r)",
            request_label,
            self.model,
            max_tokens if max_tokens is not None else "default",
            len(user_prompt or ""),
            _preview(user_prompt, min(preview_chars, 200)),
        )
        start = time.monotonic()
        resp = requests.post(self.api_url, json=body, headers=headers, timeout=self.timeout)
        elapsed = time.monotonic() - start
        logger.info("OpenRouter response: %s (status=%s, elapsed=%.2fs)", request_label, resp.status_code, elapsed)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        choice = (data.get("choices") or [{}])[0] or {}
        finish_reason = (choice.get("finish_reason") or "").strip()
        usage = data.get("usage") or {}
        logger.info(
            "OpenRouter meta: %s (finish_reason=%s, usage=%s)",
            request_label,
            finish_reason or "unknown",
            usage,
        )
        if finish_reason == "length":
            logger.warning("OpenRouter completion appears truncated (finish_reason=length): %s", request_label)

        content = choice.get("message", {}).get("content", "") or ""
        logger.info(
            "OpenRouter completion: %s (chars=%s, preview=%r)",
            request_label,
            len(content),
            _preview(content, min(preview_chars, 200)),
        )
        return content, finish_reason or "unknown", usage

    def _translate_title(self, *, source_lang: str, target_lang: str, title: str, headers: dict[str, str]) -> str:
        system_prompt = (
            "You are a translation expert. Translate the provided title from "
            f"{source_lang} to {target_lang}. "
            "Return ONLY the translated title as plain text, in a single line. "
            "No quotes, no Markdown, no code fences, no prefixes."
        )
        raw, finish_reason, _usage = self._call_openrouter(
            headers=headers,
            system_prompt=system_prompt,
            user_prompt=title,
            stop=["\n"],
            request_label=f"title {source_lang}->{target_lang}",
        )
        raw = (raw or "").strip()
        if not raw:
            logger.warning("Translation validation failed: empty title (%s -> %s)", source_lang, target_lang)
            return ""
        if "\n" in raw or "\r" in raw:
            logger.warning("Translation validation failed: multiline title (%s -> %s)", source_lang, target_lang)
            return ""
        if raw.startswith(("```", '"', "'")):
            logger.warning("Translation validation failed: title starts with quotes/code fence (%s -> %s)", source_lang, target_lang)
            return ""
        if finish_reason == "length":
            logger.warning("Title translation appears truncated (finish_reason=length): %s -> %s", source_lang, target_lang)
        return raw

    def _translate_content(self, *, source_lang: str, target_lang: str, content: str, headers: dict[str, str]) -> str:
        system_prompt = (
            "You are a translation expert. Translate the provided Markdown content from "
            f"{source_lang} to {target_lang}. Preserve Markdown structure, inline code, "
            "HTML tags, Hugo shortcodes, and URLs.\n\n"
            "Rules:\n"
            "- Always translate Markdown headings (lines starting with `#`). Keep the `#` markers and any trailing anchor "
            "like `{#...}` unchanged.\n"
            "- Do NOT translate inline code (single backticks).\n"
            "- Do NOT translate Hugo shortcodes of the form `{{< ... >}}` or `{{% ... %}}` (including their params).\n"
            "- For fenced code blocks: keep fences and language identifiers unchanged; translate ONLY comments and leave "
            "code untouched.\n"
            "- Comment markers include `#`, `//`, `--`, `;`, block comments `/* ... */`, and HTML comments `<!-- ... -->`. "
            "Preserve indentation and spacing; if unsure, leave unchanged.\n"
            "- For fenced `mermaid` blocks: translate ONLY human-visible text (labels/titles/notes/messages/edge labels) "
            "and keep all Mermaid syntax, keywords, directives, arrows, operators, punctuation, and structure unchanged. "
            "Do not add/remove lines or change indentation.\n\n"
            "Return ONLY the translated Markdown content. No title, no preface. Do not wrap the whole output in a code fence."
        )
        context_window = _context_window_size_tokens()
        encoding_name = _tiktoken_encoding_name()
        safety_margin = _translation_token_safety_margin()
        output_multiplier = _translation_output_token_multiplier()
        output_margin = _translation_output_token_margin()

        prompt_tokens = _count_tokens(system_prompt)
        content_tokens = _count_tokens(content)
        base_request_tokens = _count_request_tokens(system_prompt, "")
        chunk_budget = _compute_user_chunk_budget_tokens(system_prompt)

        logger.info(
            "Translation planning: %s -> %s (encoding=%s, context_window=%s, prompt_tokens=%s, content_tokens=%s, base_request_tokens=%s, chunk_budget=%s, output_multiplier=%s, output_margin=%s, safety_margin=%s)",
            source_lang,
            target_lang,
            encoding_name,
            context_window,
            prompt_tokens,
            content_tokens,
            base_request_tokens,
            chunk_budget,
            output_multiplier,
            output_margin,
            safety_margin,
        )

        if chunk_budget <= 0:
            logger.error(
                "Chunk budget is non-positive; cannot translate within context window (context_window=%s, base_request_tokens=%s, output_margin=%s, safety_margin=%s)",
                context_window,
                base_request_tokens,
                output_margin,
                safety_margin,
            )
            return ""

        min_chunk_budget = _translation_min_chunk_tokens()
        max_depth = _translation_max_split_depth()

        def do_translate() -> str:
            return self._translate_content_chunked(
                source_lang=source_lang,
                target_lang=target_lang,
                content=content,
                headers=headers,
                system_prompt=system_prompt,
                chunk_budget=chunk_budget,
                min_chunk_budget=min_chunk_budget,
                max_depth=max_depth,
            )

        return self._translate_with_verification(
            source_lang=source_lang,
            target_lang=target_lang,
            content=content,
            headers=headers,
            translate_fn=do_translate,
        )

    def _validate_translated_markdown(
        self,
        *,
        source_lang: str,
        target_lang: str,
        original: str,
        translated: str,
        finish_reason: str,
    ) -> str:
        """Validate translated markdown output (best-effort, avoid false positives)."""
        raw = translated or ""
        trimmed = raw.strip()
        if not trimmed:
            logger.warning("Translation validation failed: empty content (%s -> %s)", source_lang, target_lang)
            return ""

        if trimmed.lower().startswith("content:"):
            logger.warning("Translation validation failed: content starts with 'content:' (%s -> %s)", source_lang, target_lang)
            return ""

        # If the model wrapped the whole output in a code fence, try to unwrap it.
        orig_trimmed = (original or "").lstrip()
        if trimmed.startswith(("```", "~~~")) and not orig_trimmed.startswith(("```", "~~~")):
            lines = trimmed.splitlines()
            if len(lines) >= 3 and lines[0].startswith(("```", "~~~")) and lines[-1].startswith(lines[0][:3]):
                inner = "\n".join(lines[1:-1]).strip()
                if inner:
                    logger.warning("Unwrapped unexpected outer code fence from model output (%s -> %s)", source_lang, target_lang)
                    trimmed = inner

        if finish_reason == "length":
            # This is likely incomplete; let the caller decide whether to split/retry.
            return trimmed

        return trimmed

    def _translate_content_chunked(
        self,
        *,
        source_lang: str,
        target_lang: str,
        content: str,
        headers: dict[str, str],
        system_prompt: str,
        chunk_budget: int,
        min_chunk_budget: int,
        max_depth: int,
    ) -> str:
        """Translate Markdown in chunks and stitch the result back together."""
        # Keep fenced blocks intact during chunking to avoid splitting code fences.
        blocks = _parse_markdown_fences(content)
        out_parts: list[str] = []
        pending_translatable: list[str] = []

        def flush_pending() -> bool:
            nonlocal pending_translatable
            if not pending_translatable:
                return True
            pending_text = "".join(pending_translatable)
            pending_translatable = []
            translated = self._translate_chunk_with_retry(
                source_lang=source_lang,
                target_lang=target_lang,
                original_chunk=pending_text,
                headers=headers,
                system_prompt=system_prompt,
                chunk_budget=chunk_budget,
                min_chunk_budget=min_chunk_budget,
                depth=0,
                max_depth=max_depth,
                request_label_prefix="content-chunk",
            )
            if not translated:
                return False
            out_parts.append(translated)
            return True

        for blk in blocks:
            pending_translatable.append(blk.text)

        if not flush_pending():
            return ""

        return "".join(out_parts).strip()

    def _translate_chunk_with_retry(
        self,
        *,
        source_lang: str,
        target_lang: str,
        original_chunk: str,
        headers: dict[str, str],
        system_prompt: str,
        chunk_budget: int,
        min_chunk_budget: int,
        depth: int,
        max_depth: int,
        request_label_prefix: str,
    ) -> str:
        if not original_chunk.strip():
            return ""

        chunks = _split_markdown_translatable(original_chunk, chunk_budget)
        context_window = _context_window_size_tokens()
        safety_margin = _translation_token_safety_margin()
        output_multiplier = _translation_output_token_multiplier()
        output_margin = _translation_output_token_margin()

        chunk_tokens = [_count_tokens(c) for c in chunks]
        if len(chunks) <= 12:
            logger.info(
                "Translation chunk plan: %s -> %s (chunks=%s, budget=%s, chunk_tokens=%s)",
                source_lang,
                target_lang,
                len(chunks),
                chunk_budget,
                chunk_tokens,
            )
        else:
            logger.info(
                "Translation chunk plan: %s -> %s (chunks=%s, budget=%s, max_chunk_tokens=%s, total_chunk_tokens=%s)",
                source_lang,
                target_lang,
                len(chunks),
                chunk_budget,
                max(chunk_tokens) if chunk_tokens else 0,
                sum(chunk_tokens),
            )

        translated_parts: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            input_tokens = _count_tokens(chunk)
            request_tokens = _count_request_tokens(system_prompt, chunk)
            planned_output_tokens = int(input_tokens * output_multiplier) + output_margin
            allowed_output_tokens = max(0, context_window - safety_margin - request_tokens)
            chunk_max_tokens = min(planned_output_tokens, allowed_output_tokens) if planned_output_tokens > 0 else allowed_output_tokens

            logger.info(
                "Translation chunk %s/%s: input_tokens=%s, request_tokens=%s, max_tokens=%s (context_window=%s)",
                idx,
                len(chunks),
                input_tokens,
                request_tokens,
                chunk_max_tokens if chunk_max_tokens > 0 else "default",
                context_window,
            )

            # If we can't allocate any completion budget, force further splitting.
            if chunk_max_tokens <= 0 and (depth < max_depth and chunk_budget > min_chunk_budget):
                next_budget = max(min_chunk_budget, chunk_budget // 2)
                logger.warning(
                    "Chunk cannot fit in context window; splitting smaller (depth=%s -> %s, budget=%s -> %s): %s -> %s",
                    depth,
                    depth + 1,
                    chunk_budget,
                    next_budget,
                    source_lang,
                    target_lang,
                )
                sub = self._translate_chunk_with_retry(
                    source_lang=source_lang,
                    target_lang=target_lang,
                    original_chunk=chunk,
                    headers=headers,
                    system_prompt=system_prompt,
                    chunk_budget=next_budget,
                    min_chunk_budget=min_chunk_budget,
                    depth=depth + 1,
                    max_depth=max_depth,
                    request_label_prefix=f"{request_label_prefix}-split",
                )
                if not sub:
                    return ""
                translated_parts.append(_preserve_trailing_newlines(chunk, sub))
                continue
            if chunk_max_tokens <= 0:
                logger.error(
                    "Chunk cannot fit in context window and cannot split further (depth=%s/%s, budget=%s, min=%s): %s -> %s",
                    depth,
                    max_depth,
                    chunk_budget,
                    min_chunk_budget,
                    source_lang,
                    target_lang,
                )
                return ""

            raw, finish_reason, _usage = self._call_openrouter(
                headers=headers,
                system_prompt=system_prompt,
                user_prompt=chunk,
                max_tokens=chunk_max_tokens if chunk_max_tokens > 0 else None,
                request_label=f"{request_label_prefix} {source_lang}->{target_lang} {idx}/{len(chunks)}",
            )
            validated = self._validate_translated_markdown(
                source_lang=source_lang,
                target_lang=target_lang,
                original=chunk,
                translated=raw,
                finish_reason=finish_reason,
            )

            if validated and finish_reason != "length":
                translated_parts.append(_preserve_trailing_newlines(chunk, validated))
                continue

            # If truncated (or otherwise suspicious), split further and retry recursively.
            if depth >= max_depth or chunk_budget <= min_chunk_budget:
                logger.error(
                    "Chunk translation failed/truncated and cannot split further (depth=%s/%s, budget~%s, min~%s): %s -> %s",
                    depth,
                    max_depth,
                    chunk_budget,
                    min_chunk_budget,
                    source_lang,
                    target_lang,
                )
                return ""

            next_budget = max(min_chunk_budget, chunk_budget // 2)
            logger.warning(
                "Retrying chunk by splitting smaller (finish_reason=%s, depth=%s -> %s, budget~%s -> %s): %s -> %s",
                finish_reason,
                depth,
                depth + 1,
                chunk_budget,
                next_budget,
                source_lang,
                target_lang,
            )
            sub = self._translate_chunk_with_retry(
                source_lang=source_lang,
                target_lang=target_lang,
                original_chunk=chunk,
                headers=headers,
                system_prompt=system_prompt,
                chunk_budget=next_budget,
                min_chunk_budget=min_chunk_budget,
                depth=depth + 1,
                max_depth=max_depth,
                request_label_prefix=f"{request_label_prefix}-split",
            )
            if not sub:
                return ""
            translated_parts.append(_preserve_trailing_newlines(chunk, sub))

        return "".join(translated_parts)

    def _verify_translation_completeness(
        self,
        *,
        source_lang: str,
        target_lang: str,
        original: str,
        translated: str,
        headers: dict[str, str],
    ) -> tuple[bool, list[str]]:
        """Verify if translation is complete by checking for untranslated source language text.

        Returns (is_complete, untranslated_segments).
        """
        # Check if source language has a detectable character pattern
        pattern = _get_language_pattern(source_lang)
        if not pattern:
            # No pattern for this language, skip verification
            return True, []

        # Extract segments of source language characters from the translated text
        source_segments = _extract_language_segments(translated, source_lang)
        if not source_segments:
            return True, []

        # Get normalized language names for prompts
        source_lang_name = _normalize_language(source_lang)
        target_lang_name = _normalize_language(target_lang)

        # Ask LLM to verify if these segments should be preserved
        segments_text = "\n".join(f"- {seg}" for seg in source_segments[:20])  # Limit to 20 segments
        verification_prompt = (
            f"You are a translation quality checker. The following {source_lang_name} text segments were found in a translation result.\n"
            f"Determine if each segment should have been translated or if it's acceptable to keep in {source_lang_name}.\n\n"
            f"Segments that are OK to keep in {source_lang_name}:\n"
            "- Names of people (proper nouns)\n"
            "- Place names that don't have common translations in the target language\n"
            "- Brand names or product names\n"
            "- Technical terms that are commonly kept in original form\n"
            "- Quoted text that should remain as-is\n"
            "- Cultural terms with no direct translation\n\n"
            "Segments that should have been translated:\n"
            "- Regular sentences or phrases\n"
            "- Common words with clear translations\n"
            "- Descriptions, explanations, or narrative text\n"
            "- Action words, adjectives, and general vocabulary\n\n"
            f"Found {source_lang_name} segments in the {source_lang_name} -> {target_lang_name} translation:\n{segments_text}\n\n"
            "Respond with ONLY one of these two words:\n"
            "- 'COMPLETE' if all segments are acceptable to keep\n"
            "- 'INCOMPLETE' if any segment should have been translated"
        )

        try:
            response, _, _ = self._call_openrouter(
                headers=headers,
                system_prompt="You are a translation quality verification assistant. Be strict but fair.",
                user_prompt=verification_prompt,
                request_label=f"verify {source_lang}->{target_lang}",
                temperature=0.1,
            )

            response_lower = (response or "").strip().lower()
            is_complete = "complete" in response_lower and "incomplete" not in response_lower

            logger.info(
                "Translation verification: %s -> %s (source_segments=%d, result=%s)",
                source_lang,
                target_lang,
                len(source_segments),
                "COMPLETE" if is_complete else "INCOMPLETE",
            )

            return is_complete, source_segments

        except Exception as e:
            logger.warning("Translation verification failed: %s", e)
            # On error, assume translation is complete to avoid blocking
            return True, []

    def _rework_translation(
        self,
        *,
        source_lang: str,
        target_lang: str,
        original: str,
        previous_translation: str,
        untranslated_segments: list[str],
        headers: dict[str, str],
    ) -> str:
        """Rework a translation that was found to be incomplete."""
        source_lang_name = _normalize_language(source_lang)
        target_lang_name = _normalize_language(target_lang)
        segments_text = ", ".join(f"'{seg}'" for seg in untranslated_segments[:10])

        rework_prompt = (
            f"The following translation from {source_lang_name} to {target_lang_name} is incomplete. "
            f"Some {source_lang_name} text was not translated: {segments_text}\n\n"
            f"Please provide a complete translation. Translate ALL {source_lang_name} text to {target_lang_name}, "
            "except for proper nouns (names of people, places, brands) which should be transliterated or kept as-is.\n\n"
            f"Original text:\n{original}\n\n"
            f"Previous incomplete translation:\n{previous_translation}\n\n"
            "Provide the complete, corrected translation:"
        )

        system_prompt = (
            "You are a translation expert. Fix the incomplete translation by translating all remaining "
            f"{source_lang_name} text to {target_lang_name}. Preserve Markdown formatting. "
            "Return ONLY the translated content, no explanations."
        )

        try:
            response, finish_reason, _ = self._call_openrouter(
                headers=headers,
                system_prompt=system_prompt,
                user_prompt=rework_prompt,
                request_label=f"rework {source_lang}->{target_lang}",
                temperature=0.2,
            )

            validated = self._validate_translated_markdown(
                source_lang=source_lang,
                target_lang=target_lang,
                original=original,
                translated=response,
                finish_reason=finish_reason,
            )

            if validated:
                logger.info(
                    "Translation rework completed: %s -> %s (chars=%d)",
                    source_lang,
                    target_lang,
                    len(validated),
                )
                return validated

            return previous_translation

        except Exception as e:
            logger.warning("Translation rework failed: %s", e)
            return previous_translation

    def _translate_with_verification(
        self,
        *,
        source_lang: str,
        target_lang: str,
        content: str,
        headers: dict[str, str],
        translate_fn,
    ) -> str:
        """Translate content with verification and rework if needed."""
        if not _translation_verification_enabled():
            return translate_fn()

        max_attempts = _translation_max_rework_attempts()
        translated = translate_fn()

        if not translated:
            return translated

        for attempt in range(max_attempts):
            is_complete, untranslated_segments = self._verify_translation_completeness(
                source_lang=source_lang,
                target_lang=target_lang,
                original=content,
                translated=translated,
                headers=headers,
            )

            if is_complete:
                return translated

            logger.warning(
                "Translation incomplete (attempt %d/%d): %s -> %s (untranslated=%d)",
                attempt + 1,
                max_attempts,
                source_lang,
                target_lang,
                len(untranslated_segments),
            )

            reworked = self._rework_translation(
                source_lang=source_lang,
                target_lang=target_lang,
                original=content,
                previous_translation=translated,
                untranslated_segments=untranslated_segments,
                headers=headers,
            )

            if reworked == translated:
                # Rework didn't change anything, stop trying
                logger.warning(
                    "Translation rework produced no changes, accepting current translation: %s -> %s",
                    source_lang,
                    target_lang,
                )
                break

            translated = reworked

        return translated
