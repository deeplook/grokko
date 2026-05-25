"""Tests for the GrokApiClient facade."""

from __future__ import annotations

from unittest.mock import patch

from grokko.api import GrokApiClient


def _make_client() -> tuple[GrokApiClient, object]:
    with patch("grokko.api.GrokConversationClient") as MockConv:
        mock_conv = MockConv.return_value
        client = GrokApiClient([], "test-ua")
        return client, mock_conv


def test_list_conversations_delegates() -> None:
    with patch("grokko.api.GrokConversationClient") as MockConv:
        MockConv.return_value.list_conversations.return_value = [{"id": "1"}]
        client = GrokApiClient([], "ua")
        assert client.list_conversations(page_size=5) == [{"id": "1"}]
        MockConv.return_value.list_conversations.assert_called_once_with(page_size=5)


def test_get_conversation_by_index_delegates() -> None:
    with patch("grokko.api.GrokConversationClient") as MockConv:
        MockConv.return_value.get_conversation_by_index.return_value = {"id": "1"}
        client = GrokApiClient([], "ua")
        assert client.get_conversation_by_index(3) == {"id": "1"}
        MockConv.return_value.get_conversation_by_index.assert_called_once_with(3)


def test_get_conversation_by_id_delegates() -> None:
    with patch("grokko.api.GrokConversationClient") as MockConv:
        MockConv.return_value.get_conversation_by_id.return_value = {"id": "abc"}
        client = GrokApiClient([], "ua")
        assert client.get_conversation_by_id("abc") == {"id": "abc"}
        MockConv.return_value.get_conversation_by_id.assert_called_once_with("abc")


def test_get_response_node_delegates() -> None:
    with patch("grokko.api.GrokConversationClient") as MockConv:
        MockConv.return_value.get_response_node.return_value = {"responseIds": ["r1"]}
        client = GrokApiClient([], "ua")
        assert client.get_response_node("abc") == {"responseIds": ["r1"]}
        MockConv.return_value.get_response_node.assert_called_once_with("abc")


def test_load_responses_delegates() -> None:
    with patch("grokko.api.GrokConversationClient") as MockConv:
        MockConv.return_value.load_responses.return_value = [{"message": "hi"}]
        client = GrokApiClient([], "ua")
        result = client.load_responses("abc", ["r1", "r2"])
        assert result == [{"message": "hi"}]
        MockConv.return_value.load_responses.assert_called_once_with(
            "abc", ["r1", "r2"]
        )
