from __future__ import annotations

import logging
from typing import Any

from ._openai_compatible import OpenAICompatibleClient

logger = logging.getLogger(__name__)


class MiMoClient(OpenAICompatibleClient):
    """Xiaomi MiMo provider using OpenAI-compatible protocol.

    Differs from the base OpenAI-compatible client by sending
    ``max_completion_tokens`` instead of ``max_tokens`` in the
    request payload, per MiMo's API convention.
    """

    def _build_payload(self, messages: list[dict[str, str]],
                       max_tokens: int | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        return payload

    def _apply_thinking(self, thinking_enabled: bool) -> dict[str, Any] | None:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}

    def web_search(self, query: str) -> list[dict[str, str]]:
        """Execute a web search via MiMo's server-side web_search tool."""
        if not query.strip():
            return []

        logger.debug("mimo web_search query=%s", query)
        tool = {
            "type": "web_search",
            "max_keyword": 3,
            "force_search": True,
            "limit": 3,
        }
        try:
            response = self._client.chat.completions.create(  # type: ignore[call-overload]
                model=self.config.model,
                messages=[{"role": "user", "content": f"Search the web for: {query}"}],
                max_completion_tokens=4096,
                tools=[tool],
                tool_choice="auto",
            )
        except Exception as exc:
            logger.warning("mimo web_search failed for %s: %s", query[:80], exc)
            return []

        message = response.choices[0].message if response.choices else None
        if message is None:
            return []

        annotations = getattr(message, "annotations", None) or []
        results: list[dict[str, str]] = []
        for ann in annotations:
            ann_type = ann.get("type") if isinstance(ann, dict) else getattr(ann, "type", None)
            if ann_type == "url_citation":
                title = ann.get("title", "") if isinstance(ann, dict) else getattr(ann, "title", "")
                url = ann.get("url", "") if isinstance(ann, dict) else getattr(ann, "url", "")
                summary = ann.get("summary", "") if isinstance(ann, dict) else getattr(ann, "summary", "")
                results.append({
                    "title": title or "",
                    "url": url or "",
                    "snippet": summary or "",
                })
        if results:
            logger.debug("mimo web_search found %d results query=%s", len(results), query)
        else:
            logger.info("mimo web_search returned no results for %s, will fallback to DDGS", query)
        return results
