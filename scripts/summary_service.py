import hashlib
import logging
import os
from datetime import datetime
from typing import Optional

import requests
import tiktoken

from translation_service import (
    DEFAULT_CLOUDFLARE_AI_MODEL,
    DEFAULT_CLOUDFLARE_AI_READ_TIMEOUT,
    _cloudflare_ai_connect_timeout,
    _cloudflare_ai_read_timeout,
    _log_preview_chars,
    _normalize_language,
    _preview,
)

logger = logging.getLogger(__name__)

DEFAULT_CLOUDFLARE_SUMMARY_MODEL = DEFAULT_CLOUDFLARE_AI_MODEL
DEFAULT_CLOUDFLARE_SUMMARY_MAX_INPUT_CHARS = 4000
DEFAULT_CLOUDFLARE_SUMMARY_MAX_INPUT_TOKENS = 1200


class AISummarizer:
    def __init__(
        self,
        api_token: str,
        account_id: str,
        model: Optional[str] = None,
        cache_manager=None,
        timeout: int = DEFAULT_CLOUDFLARE_AI_READ_TIMEOUT,
    ):
        self.api_token = api_token
        self.account_id = account_id
        self.model = (model or os.getenv("CLOUDFLARE_SUMMARY_MODEL") or DEFAULT_CLOUDFLARE_SUMMARY_MODEL).strip()
        self.cache_manager = cache_manager
        self.timeout = timeout
        self.api_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/v1/chat/completions"
        logger.info(
            "Cloudflare AI summarizer enabled (model=%s, timeout=%ss, cache=%s)",
            self.model,
            self.timeout,
            "on" if bool(self.cache_manager) else "off",
        )

    def summarize(self, language: str, title: str, content: str) -> str:
        if not content.strip():
            return ""

        cache_key = self._build_cache_key(language, title, content)
        cached_summary = None
        if self.cache_manager:
            cached_payload = self.cache_manager.get_cached_summary(cache_key)
            if cached_payload:
                cached_summary = cached_payload.get("text") or ""
                if cached_summary:
                    logger.info(
                        "Summary cache HIT: %s (key=%s…, chars=%s)",
                        language,
                        cache_key[:12],
                        len(cached_summary),
                    )
                    return cached_summary

        logger.info(
            "Summary start: lang=%s model=%s title_preview=%r content_chars=%s",
            language,
            self.model,
            _preview(title, min(_log_preview_chars(), 120)),
            len(content or ""),
        )

        summary = self._call_cloudflare_ai(
            language=language,
            title=title,
            content=self._prepare_content(content),
        )
        if not summary:
            return ""

        if self.cache_manager:
            self.cache_manager.cache_summary(
                cache_key,
                {
                    "text": summary,
                    "language": language,
                    "model": self.model,
                    "created_at": datetime.now().isoformat(),
                },
            )
            logger.info(
                "Summary cache STORE: %s (key=%s…, chars=%s)",
                language,
                cache_key[:12],
                len(summary),
            )

        return summary

    def _build_cache_key(self, language: str, title: str, content: str) -> str:
        payload = f"{language}\n{title}\n{content}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return hashlib.sha256(f"{self.model}:{digest}".encode("utf-8")).hexdigest()

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def _prepare_content(self, content: str) -> str:
        text = (content or "").strip()
        if not text:
            return ""
        if len(text) > DEFAULT_CLOUDFLARE_SUMMARY_MAX_INPUT_CHARS:
            text = text[:DEFAULT_CLOUDFLARE_SUMMARY_MAX_INPUT_CHARS]

        enc = tiktoken.get_encoding("o200k_harmony")
        tokens = enc.encode(text)
        if len(tokens) > DEFAULT_CLOUDFLARE_SUMMARY_MAX_INPUT_TOKENS:
            text = enc.decode(tokens[:DEFAULT_CLOUDFLARE_SUMMARY_MAX_INPUT_TOKENS])
        return text

    def _build_system_prompt(self, language: str) -> str:
        language_name = _normalize_language(language)
        if not str(language_name).strip():
            language_instruction = "Write the summary in the same language as the content.\n"
        else:
            language_instruction = f"Write the summary in {language_name}.\n"
        return (
            "You write concise, high-signal blog post summaries.\n"
            f"{language_instruction}"
            "Rules:\n"
            "- Return only plain text.\n"
            "- No Markdown, no bullet points, no title prefix.\n"
            "- Prefer 1 or 2 short sentences.\n"
            "- Keep it under 220 characters if possible.\n"
            "- Write like the author's own blog blurb or opening note, not a detached abstract.\n"
            "- Preserve the source tone and level of specificity.\n"
            "- Lead with the concrete topic, takeaway, or tension.\n"
            "- Avoid stock openings such as 'This post', 'This article', or 'In this article'.\n"
            "- Ignore boilerplate, navigation, translation notices, and code-only sections."
        )

    def _call_cloudflare_ai(self, *, language: str, title: str, content: str) -> str:
        system_prompt = self._build_system_prompt(language)
        user_prompt = f"Title:\n{title}\n\nContent:\n{content}"
        response = requests.post(
            self.api_url,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
            },
            headers=self._build_headers(),
            timeout=(_cloudflare_ai_connect_timeout(), self.timeout),
        )
        if response.status_code in (429, 500, 502, 503, 504):
            for attempt in range(2):
                logger.warning(
                    "Cloudflare AI summary request retrying after status=%s (attempt=%s)",
                    response.status_code,
                    attempt + 2,
                )
                response = requests.post(
                    self.api_url,
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                    },
                    headers=self._build_headers(),
                    timeout=(_cloudflare_ai_connect_timeout(), self.timeout),
                )
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            raise RuntimeError(str(data["errors"]))

        text = ((data.get("choices") or [{}])[0] or {}).get("message", {}).get("content", "") or ""
        summary = " ".join(text.strip().split())
        if not summary:
            return ""
        if summary.startswith("```") and summary.endswith("```"):
            summary = summary.strip("`").strip()
        return summary
