from __future__ import annotations

import logging
import re
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
        """Post an agent message into a LiveAgent conversation (API v1).

        Requires a real API **v1** key. A v3 key will get 403 on this endpoint.
        """
        api_key = (self.config.api_v1_key or "").strip()
        if self.config.dry_run:
            logger.info("DRY_RUN post_reply %s -> %s", conversation_id, message[:200])
            import uuid

            return {"dry_run": True, "external_stub": f"dry-{conversation_id}-{uuid.uuid4().hex[:12]}"}
        if not api_key:
            raise RuntimeError(
                "LIVEAGENT_API_V1_KEY is empty; cannot post replies. "
                "API v3 keys do not work on /api/conversations/.../messages"
            )
        data: dict[str, Any] = {
            "apikey": api_key,
            "message": message,
            "type": "N" if as_note else "M",
            # Chat/button tickets: avoid email department template wrapping
            "do_not_send_mail": "Y",
            "is_html_message": "N",
            "use_template": "N",
        }
        if self.config.agent_email:
            data["useridentifier"] = self.config.agent_email
        url = f"{self.config.v1_base}/conversations/{conversation_id}/messages"
        r = self._client.post(url, data=data)
        if r.status_code >= 400:
            logger.error("post_reply failed %s %s body=%s", r.status_code, r.text[:500], message[:120])
            r.raise_for_status()
        logger.info("post_reply ok conversation=%s status=%s", conversation_id, r.status_code)
        try:
            body = r.json() if r.content else {"status_code": r.status_code}
        except Exception:
            body = {"status_code": r.status_code, "text": r.text}
        # Normalize success payloads that only return {response:{status:OK}}
        if isinstance(body, dict) and not (
            body.get("id") or body.get("messageid") or (body.get("response") or {}).get("messageid")
        ):
            body["external_stub"] = f"la-{conversation_id}-{r.status_code}"
        return body

    def list_agent_directory(self) -> dict[str, set[str]]:
        """Best-effort agent ids / emails / names from LiveAgent."""
        ids: set[str] = set()
        emails: set[str] = set()
        names: set[str] = set()
        for path in ("agents", "users"):
            try:
                r = self._client.get(
                    f"{self.config.v3_base}/{path}",
                    headers=self._v3_headers(),
                    params={"_perPage": 100},
                )
                if r.status_code >= 400:
                    continue
                data = r.json()
                rows = data if isinstance(data, list) else data.get("data") or []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    for key in ("id", "userid", "user_id"):
                        val = row.get(key)
                        if val:
                            ids.add(str(val))
                    for key in ("email", "user_email", "mail"):
                        val = row.get(key)
                        if val:
                            emails.add(str(val).strip().lower())
                    for key in ("name", "firstname", "lastname", "user_name"):
                        val = row.get(key)
                        if val:
                            names.add(str(val).strip().lower())
                    # combine first+last when present
                    first = str(row.get("firstname") or "").strip()
                    last = str(row.get("lastname") or "").strip()
                    if first or last:
                        names.add(f"{first} {last}".strip().lower())
            except Exception as exc:  # noqa: BLE001
                logger.debug("list_agent_directory %s failed: %s", path, exc)
        if self.config.agent_email:
            emails.add(self.config.agent_email.strip().lower())
        names.update({"pingo cs", "pin go cs", "pingo"})
        return {"ids": ids, "emails": emails, "names": names}

    def list_agent_user_ids(self) -> set[str]:
        return self.list_agent_directory()["ids"]

    @staticmethod
    def flatten_messages(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize LA message groups into flat message dicts."""
        flat: list[dict[str, Any]] = []
        for group in groups:
            group_id = group.get("id") or group.get("messagegroupid")
            group_userid = group.get("userid")
            group_type = group.get("type")
            group_email = (
                group.get("user_email")
                or group.get("email")
                or group.get("userid_email")
                or group.get("agent_email")
            )
            group_name = (
                group.get("user_full_name")
                or group.get("user_name")
                or group.get("name")
                or group.get("userid_name")
                or group.get("agent_name")
                or group.get("username")
            )
            for msg in group.get("messages") or []:
                msg_type = msg.get("type")
                if msg_type not in {"M", "Y", "N"}:
                    continue
                body = (msg.get("message") or "").strip()
                if not body:
                    continue
                mid = str(msg.get("id") or f"{group_id}:{msg.get('datecreated')}:{hash(body) & 0xFFFF}")
                is_note = msg_type == "N"
                userid = msg.get("userid") or group_userid
                flat.append(
                    {
                        "external_id": mid,
                        "body": body,
                        "userid": userid,
                        "user_email": msg.get("user_email") or msg.get("email") or group_email,
                        "user_name": msg.get("user_name") or msg.get("name") or group_name,
                        "datecreated": msg.get("datecreated"),
                        "is_note": is_note,
                        "group_type": group_type,
                        "raw_type": msg_type,
                        "raw_group": {k: group.get(k) for k in ("type", "userid", "user_type", "role") if k in group},
                    }
                )
        return flat

    _AGENT_BODY_RE = re.compile(
        r"(layanan\s*pelanggan|customer\s*service|ada\s+yang\s+bisa\s+saya\s+bantu|"
        r"how\s+can\s+i\s+(help|assist)|saya\s+\w+\s+dari\s+.*pingo|"
        r"i\s*('?m|am)\s+\w+\s+from\s+pingo|from\s+pingo\s+customer|"
        r"pingo\s+cs\b|agent\s+manusia)",
        re.IGNORECASE,
    )

    @classmethod
    def classify_sender(
        cls,
        item: dict[str, Any],
        *,
        agent_user_ids: set[str] | None = None,
        agent_emails: set[str] | None = None,
        agent_names: set[str] | None = None,
        agent_email: str = "",
        contact_id: str = "",
        known_ai_bodies: set[str] | None = None,
    ) -> tuple[str, str]:
        """Return (direction, sender_type) using LiveAgent userid + /agents.

        LiveChat visitor userid != ticket owner_contactid. Agent messages use
        staff userid from GET /agents (e.g. PinGo CS). Do NOT treat "any userid"
        as agent — that mislabels visitor pre-chat fields as PinGo CS.
        """
        if item.get("is_note"):
            return "note", "system"
        body = (item.get("body") or "").strip()
        if known_ai_bodies and body in known_ai_bodies:
            return "outbound", "ai"

        userid = str(item.get("userid") or "").strip()
        email = str(item.get("user_email") or "").strip().lower()
        name = str(item.get("user_name") or "").strip().lower()
        agent_email_l = (agent_email or "").strip().lower()
        ids = set(agent_user_ids or set())
        emails = set(agent_emails or set())
        if agent_email_l:
            emails.add(agent_email_l)
        names = set(agent_names or set())

        # Primary: LiveAgent agent id from GET /agents
        if userid and ids and userid in ids:
            return "outbound", "agent"
        if email and email in emails:
            return "outbound", "agent"
        if name and name in names:
            return "outbound", "agent"

        # Fallback only when agent directory failed to load
        if not ids and body and cls._AGENT_BODY_RE.search(body):
            return "outbound", "agent"

        return "inbound", "customer"


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
