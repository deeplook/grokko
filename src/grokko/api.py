"""Backward-compatible API facade around conversation clients."""

from __future__ import annotations

from typing import Any

from grokko.conversations import GrokConversationClient


class GrokApiClient:
    """Compatibility facade exposing conversation helpers."""

    def __init__(self, cookies: list[dict[str, Any]], user_agent: str) -> None:
        """Create sub-clients that share one authenticated browser session."""
        self._conversations = GrokConversationClient(cookies, user_agent)

    def list_conversations(self, page_size: int = 1) -> list[dict[str, Any]]:
        """Return the newest conversations visible to the current account."""
        return self._conversations.list_conversations(page_size=page_size)

    def get_conversation_by_index(self, index: int) -> dict[str, Any] | None:
        """Return one conversation by zero-based recency index."""
        return self._conversations.get_conversation_by_index(index)

    def get_conversation_by_id(self, conversation_id: str) -> dict[str, Any]:
        """Fetch one conversation metadata object by its conversation ID."""
        return self._conversations.get_conversation_by_id(conversation_id)

    def get_response_node(self, conversation_id: str) -> dict[str, Any]:
        """Fetch the response-node payload that points to message content."""
        return self._conversations.get_response_node(conversation_id)

    def load_responses(
        self, conversation_id: str, response_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Load concrete response payloads for the supplied response IDs."""
        return self._conversations.load_responses(conversation_id, response_ids)
