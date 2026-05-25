"""Conversation-specific REST client for Grok chat history APIs."""

from __future__ import annotations

import json
from typing import Any

from grokko._http import GrokApiError, GrokRestClient, extract_list


class GrokConversationClient(GrokRestClient):
    """Read conversations, response nodes, and transcripts from Grok."""

    def list_conversations(self, page_size: int = 1) -> list[dict[str, Any]]:
        """List the newest conversations visible to the current account."""
        resp = self._get(f"/rest/app-chat/conversations?pageSize={page_size}")
        return extract_list(resp, "conversations")

    def get_conversation_by_index(self, index: int) -> dict[str, Any] | None:
        """Return the conversation at a zero-based position in recency order."""
        conversations = self.list_conversation_range(index, index + 1)
        return conversations[0] if conversations else None

    def list_conversation_range(self, start: int, stop: int) -> list[dict[str, Any]]:
        """Return conversations in the half-open recency slice `[start, stop)`."""
        if start < 0 or stop < 0 or stop < start:
            raise ValueError("conversation slice must satisfy 0 <= start <= stop")
        if start == stop:
            return []

        page_size = 60
        target_count = stop - start
        collected = 0
        token: str | None = None
        selected: list[dict[str, Any]] = []
        while True:
            need = stop - collected
            size = min(need, page_size)
            path = f"/rest/app-chat/conversations?pageSize={size}"
            if token:
                path += f"&pageToken={token}"
            resp = self._get(path)
            page = extract_list(resp, "conversations")
            if not page:
                return selected

            page_start = max(start - collected, 0)
            page_stop = min(stop - collected, len(page))
            if page_start < page_stop:
                selected.extend(page[page_start:page_stop])
                if len(selected) >= target_count:
                    return selected[:target_count]

            collected += len(page)
            token = resp.get("nextPageToken") if isinstance(resp, dict) else None
            if not token:
                return selected

    def get_conversation_by_id(self, conversation_id: str) -> dict[str, Any]:
        """Fetch one conversation metadata object by conversation ID."""
        result = self._get(f"/rest/app-chat/conversations/{conversation_id}")
        if not isinstance(result, dict):
            raise GrokApiError(
                "Unexpected conversation shape — Grok API may have changed: "
                f"{json.dumps(result)[:200]}"
            )
        return result

    def get_response_node(self, conversation_id: str) -> dict[str, Any]:
        """Fetch the response-node structure that points to message payloads."""
        result = self._get(
            f"/rest/app-chat/conversations/{conversation_id}/response-node"
        )
        if not isinstance(result, dict):
            raise GrokApiError(
                "Unexpected response-node shape — Grok API may have changed: "
                f"{json.dumps(result)[:200]}"
            )
        return result

    def load_responses(
        self, conversation_id: str, response_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Load concrete response payloads for a conversation transcript."""
        resp = self._post(
            f"/rest/app-chat/conversations/{conversation_id}/load-responses",
            {"responseIds": response_ids},
        )
        return extract_list(resp, "responses")
