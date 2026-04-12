import hashlib
import logging
import os
from datetime import datetime
from typing import Optional

import requests

from translation_service import (
    DEFAULT_OPENROUTER_APP_NAME,
    DEFAULT_OPENROUTER_SITE_URL,
    _log_preview_chars,
    _normalize_language,
    _preview,
)

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_SUMMARY_MODEL = "google/gemma-4-31b-it:free"


class OpenRouterSummarizer:
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
        self.model = (model or os.getenv("OPENROUTER_SUMMARY_MODEL") or DEFAULT_OPENROUTER_SUMMARY_MODEL).strip()
        self.cache_manager = cache_manager
        self.site_url = site_url
        self.app_name = app_name
        self.timeout = timeout
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        logger.info(
            "OpenRouter summarizer enabled (model=%s, timeout=%ss, cache=%s)",
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

        summary = self._call_openrouter(language=language, title=title, content=content)
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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name
        return headers

    def _call_openrouter(self, *, language: str, title: str, content: str) -> str:
        language_name = _normalize_language(language)
        if not str(language_name).strip():
            language_instruction = "Write the summary in the same language as the content.\n"
        else:
            language_instruction = f"Write the summary in {language_name}.\n"
        system_prompt = (
            "You write concise, high-signal blog post summaries.\n"
            f"{language_instruction}"
            "Rules:\n"
            "- Return only plain text.\n"
            "- No Markdown, no bullet points, no title prefix.\n"
            "- Prefer 1 or 2 short sentences.\n"
            "- Keep it under 220 characters if possible.\n"
            "- Focus on the core topic and value of the article.\n"
            "- Ignore boilerplate, navigation, translation notices, and code-only sections."
        )
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
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]))

        text = ((data.get("choices") or [{}])[0] or {}).get("message", {}).get("content", "") or ""
        summary = " ".join(text.strip().split())
        if not summary:
            return ""
        if summary.startswith("```") and summary.endswith("```"):
            summary = summary.strip("`").strip()
        return summary
