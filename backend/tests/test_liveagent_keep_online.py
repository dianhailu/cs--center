"""Unit checks for LiveAgent Devices keep-online helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from app.channels.liveagent import LiveAgentClient, LiveAgentConfig


def _resp(status_code: int = 200, *, json=None, text: str = "") -> httpx.Response:
    request = httpx.Request("GET", "https://example.ladesk.com/api/v3/stub")
    if json is not None:
        return httpx.Response(status_code, json=json, request=request)
    return httpx.Response(status_code, text=text, request=request)


def _client(*, dry_run: bool = False, agent_user_id: str = "") -> LiveAgentClient:
    return LiveAgentClient(
        LiveAgentConfig(
            base_url="https://example.ladesk.com",
            api_v3_key="v3",
            api_v1_key="v1-key",
            agent_email="agent@example.com",
            dry_run=dry_run,
            auto_transfer=True,
            agent_user_id=agent_user_id,
            chat_department_id="",
        )
    )


def test_resolve_agent_id_uses_override() -> None:
    la = _client(agent_user_id="abc123")
    la._client = MagicMock()
    assert la.resolve_agent_id() == "abc123"
    la._client.get.assert_not_called()


def test_resolve_agent_id_from_email() -> None:
    la = _client()
    la._client = MagicMock()
    la._client.get.return_value = _resp(
        json=[{"id": "t84l1kx7", "email": "agent@example.com", "name": "PinGo CS"}],
    )
    assert la.resolve_agent_id() == "t84l1kx7"


def test_ensure_reuses_web_chat_device() -> None:
    la = _client()
    la._client = MagicMock()
    la._client.get.return_value = _resp(
        json=[
            {"id": 2, "agent_id": "t84", "type": "W", "service_type": "M", "online_status": "F"},
            {"id": 4, "agent_id": "t84", "type": "W", "service_type": "T", "online_status": "F"},
        ],
    )
    device = la.ensure_external_chat_device("t84")
    assert device["id"] == 4
    la._client.post.assert_not_called()


def test_set_online_puts_required_fields() -> None:
    la = _client()
    la._client = MagicMock()
    la._client.put.return_value = _resp(
        json={"id": 4, "agent_id": "t84", "type": "W", "service_type": "T", "online_status": "N"},
    )
    result = la.set_online(4, agent_id="t84", device_type="W", service_type="T")
    assert result["online_status"] == "N"
    call = la._client.put.call_args
    assert call.args[0].endswith("/api/v3/devices/4")
    assert call.kwargs["json"] == {
        "agent_id": "t84",
        "type": "W",
        "service_type": "T",
        "online_status": "N",
        "preset_status": "N",
    }


def test_set_department_chat_puts_required_fields() -> None:
    la = _client()
    la._client = MagicMock()
    la._client.put.return_value = _resp(
        json={"device_id": 4, "department_id": "default", "user_id": "t84", "online_status": "N"},
    )
    la.set_department_chat(4, "default", user_id="t84")
    call = la._client.put.call_args
    assert "/devices/4/departments/default" in call.args[0]
    assert call.kwargs["json"]["device_id"] == 4
    assert call.kwargs["json"]["department_id"] == "default"
    assert call.kwargs["json"]["user_id"] == "t84"
    assert call.kwargs["json"]["online_status"] == "N"


def test_keep_agent_online_orchestrates() -> None:
    la = _client()
    la.resolve_agent_id = MagicMock(return_value="t84")  # type: ignore[method-assign]
    la.ensure_external_chat_device = MagicMock(  # type: ignore[method-assign]
        return_value={"id": 4, "type": "W", "service_type": "T"}
    )
    la.set_online = MagicMock(return_value={"online_status": "N"})  # type: ignore[method-assign]
    la.resolve_chat_department_id = MagicMock(return_value="default")  # type: ignore[method-assign]
    la.set_department_chat = MagicMock(return_value={})  # type: ignore[method-assign]
    la.get_online_status = MagicMock(  # type: ignore[method-assign]
        return_value={"agents": [{"id": "t84", "onlineStatus": "TR"}], "agent_status": None}
    )
    result = la.keep_agent_online()
    assert result["chat_online"] is True
    assert result["device_id"] == 4
    la.set_online.assert_called_once()
    la.set_department_chat.assert_called_once()


def test_agent_chat_online_helpers() -> None:
    assert LiveAgentClient._agent_chat_online("TR") is True
    assert LiveAgentClient._agent_chat_online("") is False
    assert LiveAgentClient._agent_chat_online("F") is False
    assert LiveAgentClient._agent_chat_online("MR") is None
