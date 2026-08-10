"""Lightweight unit checks for LiveAgent transfer_to_agent."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from app.channels.liveagent import LiveAgentClient, LiveAgentConfig


def _client(*, dry_run: bool = False) -> LiveAgentClient:
    return LiveAgentClient(
        LiveAgentConfig(
            base_url="https://example.ladesk.com",
            api_v3_key="v3",
            api_v1_key="v1-key",
            agent_email="agent@example.com",
            dry_run=dry_run,
            auto_transfer=True,
        )
    )


def test_transfer_to_agent_dry_run_skips_http() -> None:
    la = _client(dry_run=True)
    la._client = MagicMock()
    result = la.transfer_to_agent("CONV1")
    assert result == {"dry_run": True}
    la._client.put.assert_not_called()


def test_transfer_to_agent_puts_attendants() -> None:
    la = _client()
    ok = httpx.Response(200, json={"response": {"status": "OK", "statuscode": 0}})
    status_ok = httpx.Response(200, json={"response": {"status": "OK"}})
    la._client = MagicMock()
    la._client.put.side_effect = [ok, status_ok]

    result = la.transfer_to_agent("CONV1")

    assert result.get("transferred_to") == "agent@example.com"
    first_call = la._client.put.call_args_list[0]
    assert first_call.args[0].endswith("/api/conversations/CONV1/attendants")
    assert first_call.kwargs["data"]["agentidentifier"] == "agent@example.com"
    assert first_call.kwargs["data"]["apikey"] == "v1-key"


def test_transfer_to_agent_harmless_already_assigned() -> None:
    la = _client()
    already = httpx.Response(
        400,
        json={"response": {"status": "ERROR", "errormessage": "Conversation already assigned"}},
    )
    la._client = MagicMock()
    la._client.put.return_value = already

    result = la.transfer_to_agent("CONV1")

    assert result.get("skipped") is True
    assert la._client.put.call_count == 1


def test_transfer_to_agent_http200_api_error_raises_unless_harmless() -> None:
    la = _client()
    already = httpx.Response(
        200,
        json={"response": {"status": "ERROR", "errormessage": "Ticket is already assigned"}},
    )
    la._client = MagicMock()
    la._client.put.return_value = already
    result = la.transfer_to_agent("CONV1")
    assert result.get("skipped") is True


def test_is_harmless_transfer_error() -> None:
    assert LiveAgentClient._is_harmless_transfer_error(400, "already assigned to agent")
    assert not LiveAgentClient._is_harmless_transfer_error(403, "permission denied")
