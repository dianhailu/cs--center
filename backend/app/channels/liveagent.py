from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LiveAgentConfig:
    base_url: str
    api_v3_key: str
    api_v1_key: str = ""
    agent_email: str = ""
    dry_run: bool = True

    @property
    def v3_base(self) -> str:
        return self.base_url.rstrip("/") + "/api/v3"

    @property
    def v1_base(self) -> str:
        return self.base_url.rstrip("/") + "/api"


class LiveAgentClient:
    def __init__(self, config: LiveAgentConfig):
        self.config = config
        self._client = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def _v3_headers(self) -> dict[str, str]:
        return {
            "apikey": self.config.api_v3_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def ping(self) -> Any:
        r = self._client.get(f"{self.config.v3_base}/ping", headers=self._v3_headers())
        r.raise_for_status()
        return r.json()

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        r = self._client.get(
            f"{self.config.v3_base}/tickets/{ticket_id}",
            headers=self._v3_headers(),
        )
        r.raise_for_status()
        return r.json()

    def get_ticket_messages(self, ticket_id: str, per_page: int = 100) -> list[dict[str, Any]]:
        """Fetch all message groups for a ticket (paginated)."""
        all_groups: list[dict[str, Any]] = []
        page = 1
        while True:
            r = self._client.get(
                f"{self.config.v3_base}/tickets/{ticket_id}/messages",
                headers=self._v3_headers(),
                params={"_perPage": per_page, "_page": page, "_sortDir": "ASC"},
            )
            r.raise_for_status()
            data = r.json()
            batch = data if isinstance(data, list) else []
            if not batch:
                break
            all_groups.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
            if page > 200:
                logger.warning("message pagination stopped at page 200 for ticket %s", ticket_id)
                break
        return all_groups

    def list_recent_tickets(self, per_page: int = 50) -> list[dict[str, Any]]:
        return self.list_tickets(page=1, per_page=per_page)

    def list_tickets(
        self,
        *,
        page: int = 1,
        per_page: int = 50,
        sort_field: str = "date_changed",
        sort_dir: str = "DESC",
    ) -> list[dict[str, Any]]:
        r = self._client.get(
            f"{self.config.v3_base}/tickets",
            headers=self._v3_headers(),
            params={
                "_page": page,
                "_perPage": per_page,
                "_sortDir": sort_dir,
                "_sortField": sort_field,
            },
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def update_ticket(self, ticket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.config.dry_run:
            logger.info("DRY_RUN update_ticket %s %s", ticket_id, payload)
            return {"dry_run": True}
        r = self._client.put(
            f"{self.config.v3_base}/tickets/{ticket_id}",
            headers=self._v3_headers(),
            json=payload,
        )
        if r.status_code >= 400:
            logger.error("update_ticket failed %s %s", r.status_code, r.text[:500])
            r.raise_for_status()
        return r.json() if r.content else {}

    def list_tags(self) -> list[dict[str, Any]]:
        r = self._client.get(
            f"{self.config.v3_base}/tags",
            headers=self._v3_headers(),
            params={"_perPage": 100},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def resolve_tag_ids(self, names: list[str]) -> list[str]:
        existing = self.list_tags()
        by_name = {(t.get("name") or "").lower(): t for t in existing}
        ids: list[str] = []
        for name in names:
            found = by_name.get(name.lower())
            if found and found.get("id"):
                ids.append(found["id"])
                continue
            created = self._client.post(
                f"{self.config.v3_base}/tags",
                headers=self._v3_headers(),
                json={
                    "name": name,
                    "color": "FFFFFF",
                    "background_color": "E67E22" if "handoff" in name else "27AE60",
                    "is_public": "N",
                },
            )
            if created.status_code < 400:
                body = created.json() if created.content else {}
                ids.append(body.get("id") or name)
            else:
                ids.append(name)
        return ids

    def add_tags(self, ticket_id: str, tags: list[str]) -> dict[str, Any]:
        if self.config.dry_run:
            logger.info("DRY_RUN add_tags %s %s", ticket_id, tags)
            return {"dry_run": True}
        tag_ids = self.resolve_tag_ids(tags)
        ticket = self.get_ticket(ticket_id)
        existing = ticket.get("tags") or []
        if isinstance(existing, str):
            existing = [t for t in existing.split(",") if t]
        merged = list(dict.fromkeys([*existing, *tag_ids]))
        return self.update_ticket(ticket_id, {"tags": merged})

    def post_reply(
        self,
        conversation_id: str,
        message: str,
        *,
        as_note: bool = False,
    ) -> dict[str, Any]:
        api_key = self.config.api_v1_key or self.config.api_v3_key
        data: dict[str, Any] = {
            "apikey": api_key,
            "message": message,
            "type": "N" if as_note else "M",
            "do_not_send_mail": "N",
            "is_html_message": "N",
        }
        if self.config.agent_email:
            data["useridentifier"] = self.config.agent_email
        url = f"{self.config.v1_base}/conversations/{conversation_id}/messages"
        if self.config.dry_run:
            logger.info("DRY_RUN post_reply %s -> %s", conversation_id, message[:200])
            import uuid

            return {"dry_run": True, "external_stub": f"dry-{conversation_id}-{uuid.uuid4().hex[:12]}"}
        r = self._client.post(url, data=data)
        if r.status_code >= 400:
            logger.error("post_reply failed %s %s", r.status_code, r.text[:500])
            r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text}

    @staticmethod
    def flatten_messages(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize LA message groups into flat message dicts."""
        flat: list[dict[str, Any]] = []
        for group in groups:
            group_id = group.get("id") or group.get("messagegroupid")
            group_userid = group.get("userid")
            group_type = group.get("type")
            for msg in group.get("messages") or []:
                msg_type = msg.get("type")
                if msg_type not in {"M", "Y", "N"}:
                    continue
                body = (msg.get("message") or "").strip()
                if not body:
                    continue
                mid = str(msg.get("id") or f"{group_id}:{msg.get('datecreated')}:{hash(body) & 0xFFFF}")
                # Heuristic: notes are internal; otherwise treat as customer unless marked otherwise
                is_note = msg_type == "N"
                flat.append(
                    {
                        "external_id": mid,
                        "body": body,
                        "userid": msg.get("userid") or group_userid,
                        "datecreated": msg.get("datecreated"),
                        "is_note": is_note,
                        "group_type": group_type,
                        "raw_type": msg_type,
                    }
                )
        return flat


def client_from_connection(conn: Any) -> LiveAgentClient:
    return LiveAgentClient(
        LiveAgentConfig(
            base_url=conn.base_url,
            api_v3_key=conn.api_v3_key,
            api_v1_key=conn.api_v1_key,
            agent_email=conn.agent_email,
            dry_run=bool(conn.dry_run),
        )
    )
