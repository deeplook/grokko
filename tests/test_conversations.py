from __future__ import annotations

import pytest

from grokko._http import GrokApiError
from grokko.conversations import GrokConversationClient


class FakeConversationClient(GrokConversationClient):
    def __init__(self) -> None:
        super().__init__([], "ua")
        self.get_responses: list[object] = []
        self.post_responses: list[object] = []
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, object]] = []

    def _get(self, path: str) -> object:
        self.get_calls.append(path)
        return self.get_responses.pop(0)

    def _post(self, path: str, body: object) -> object:
        self.post_calls.append((path, body))
        return self.post_responses.pop(0)


def test_list_conversations_and_load_responses() -> None:
    client = FakeConversationClient()
    client.get_responses = [{"conversations": [{"conversationId": "c1"}]}]
    client.post_responses = [{"responses": [{"responseId": "r1"}]}]

    assert client.list_conversations(page_size=2) == [{"conversationId": "c1"}]
    assert client.load_responses("c1", ["r1"]) == [{"responseId": "r1"}]
    assert client.post_calls == [
        ("/rest/app-chat/conversations/c1/load-responses", {"responseIds": ["r1"]})
    ]


def test_get_conversation_by_index_and_range_paginate() -> None:
    client = FakeConversationClient()
    client.get_responses = [
        {
            "conversations": [{"conversationId": "c0"}, {"conversationId": "c1"}],
            "nextPageToken": "p2",
        },
        {"conversations": [{"conversationId": "c2"}, {"conversationId": "c3"}]},
    ]

    assert client.get_conversation_by_index(2) == {"conversationId": "c2"}
    assert client.get_calls == [
        "/rest/app-chat/conversations?pageSize=3",
        "/rest/app-chat/conversations?pageSize=1&pageToken=p2",
    ]

    client = FakeConversationClient()
    client.get_responses = [
        {
            "conversations": [{"conversationId": "c0"}, {"conversationId": "c1"}],
            "nextPageToken": "p2",
        },
        {
            "conversations": [{"conversationId": "c2"}, {"conversationId": "c3"}],
            "nextPageToken": "p3",
        },
        {"conversations": [{"conversationId": "c4"}]},
    ]
    assert client.list_conversation_range(1, 4) == [
        {"conversationId": "c1"},
        {"conversationId": "c2"},
        {"conversationId": "c3"},
    ]


def test_search_conversations_attaches_highlights() -> None:
    client = FakeConversationClient()
    client.get_responses = [
        {
            "conversations": [
                {"conversationId": "c1", "title": "Python tips"},
                {"conversationId": "c2", "title": "No highlight here"},
            ],
            "textSearchMatches": [
                {
                    "conversation": {"conversationId": "c1"},
                    "matchType": "MATCH_MESSAGE",
                    "highlight": "some python snippet",
                }
            ],
        }
    ]

    results = client.search_conversations("python", page_size=10)

    assert client.get_calls == [
        "/rest/app-chat/conversations?pageSize=10&searchQuery=python"
    ]
    assert results == [
        {
            "conversation": {"conversationId": "c1", "title": "Python tips"},
            "highlight": "some python snippet",
            "matchType": "MATCH_MESSAGE",
        },
        {
            "conversation": {"conversationId": "c2", "title": "No highlight here"},
            "highlight": None,
            "matchType": None,
        },
    ]


def test_search_conversations_encodes_query() -> None:
    client = FakeConversationClient()
    client.get_responses = [{"conversations": []}]

    client.search_conversations("py & spaces")

    assert client.get_calls == [
        "/rest/app-chat/conversations?pageSize=60&searchQuery=py%20%26%20spaces"
    ]


def test_list_conversation_range_validates_bounds() -> None:
    client = FakeConversationClient()

    with pytest.raises(ValueError):
        client.list_conversation_range(-1, 1)
    with pytest.raises(ValueError):
        client.list_conversation_range(2, 1)
    assert client.list_conversation_range(2, 2) == []


def test_get_conversation_and_response_node_require_dicts() -> None:
    client = FakeConversationClient()
    client.get_responses = [["bad"], ["bad"]]

    with pytest.raises(GrokApiError, match="Unexpected conversation shape"):
        client.get_conversation_by_id("c1")
    with pytest.raises(GrokApiError, match="Unexpected response-node shape"):
        client.get_response_node("c1")
