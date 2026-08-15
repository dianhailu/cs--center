"""Unit checks for LiveAgent panel pickUpChat / createAnswer helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.channels.liveagent import LiveAgentClient, LiveAgentConfig


def _client(**kwargs) -> LiveAgentClient:
    base = dict(
        base_url="https://example.ladesk.com",
        api_v3_key="v3",
        api_v1_key="v1",
        agent_email="agent@example.com",
        agent_user_id="agent1",
        dry_run=False,
        panel_accept=True,
    )
    base.update(kwargs)
    return LiveAgentClient(LiveAgentConfig(**base))


def test_accept_chat_dry_run():
    la = _client(dry_run=True)
    out = la.accept_chat("ticket1")
    assert out["answered"] == "Y"
    assert out["dry_run"] is True


def test_accept_chat_pickup_and_join():
    la = _client()
    assert la._client.follow_redirects is True
    with (
        patch.object(la, "panel_login", return_value="SESSIONTOKEN123456789012345678"),
        patch.object(
            la,
            "panel_rpc",
            side_effect=[
                [["name", "value"], ["answered", "Y"]],
                {"S": "Y"},
            ],
        ) as rpc,
    ):
        out = la.accept_chat("ticket1")
    assert out["answered"] == "Y"
    assert out["session"] == "SESSIONTOKEN123456789012345678"
    assert out["join"] == {"S": "Y"}
    assert rpc.call_count == 2
    assert rpc.call_args_list[0].args[0]["M"] == "pickUpChat"
    assert rpc.call_args_list[1].args[0]["M"] == "joinOperator"


def test_create_chat_answer_raises_on_panel_error():
    la = _client()
    with (
        patch.object(la, "panel_login", return_value="SESSIONTOKEN123456789012345678"),
        patch.object(la, "resolve_chat_group_id", return_value="01a-group-uuid"),
        patch.object(la, "panel_rpc", side_effect=RuntimeError("panel_rpc error M=createAnswer: 您没有权限执行此操作。")),
    ):
        with pytest.raises(RuntimeError, match="权限"):
            la.create_chat_answer("ticket1", "hello")


def test_create_chat_answer_uses_type_c_group_id_not_ticket_id():
    la = _client()
    with (
        patch.object(la, "panel_login", return_value="SESSIONTOKEN123456789012345678"),
        patch.object(la, "resolve_chat_group_id", return_value="01a004dc-group-uuid") as resolve,
        patch.object(
            la,
            "panel_rpc",
            return_value=[
                ["name", "value"],
                ["messageid", "msg-1"],
                ["message_groupid", "01a004dc-group-uuid"],
            ],
        ) as rpc,
    ):
        out = la.create_chat_answer("ticket1", "hello visitor")
    resolve.assert_called_once_with("ticket1")
    payload = rpc.call_args.args[0]
    assert payload["M"] == "createAnswer"
    assert payload["chatId"] == "01a004dc-group-uuid"
    assert payload["chatId"] != "ticket1"
    assert payload["text"] == "hello visitor"
    assert out["path"] == "type_c"
    assert out["external_stub"] == "msg-1"
    assert out["chat_group_id"] == "01a004dc-group-uuid"


def test_resolve_chat_group_id_picks_latest_type_c():
    la = _client()
    with patch.object(
        la,
        "get_ticket_messages",
        return_value=[
            {"id": "g-start", "type": "S"},
            {"id": "01a-old", "type": "C"},
            {"id": "g-note", "type": "5"},
            {"id": "01a-new", "type": "C"},
        ],
    ):
        assert la.resolve_chat_group_id("ticket1") == "01a-new"


def test_panel_form_value():
    resp = [["name", "value"], ["answered", "Y"], ["other", "1"]]
    assert LiveAgentClient._panel_form_value(resp, "answered") == "Y"
    assert LiveAgentClient._panel_form_value(resp, "missing") is None
