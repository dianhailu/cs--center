from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_PANEL_CHAT_ANSWERER = "Qu\\La\\ChatGateway\\Infrastructure\\Rpc\\ChatAnswererRpc"
_PANEL_CHAT_JOINER = "Qu\\La\\ChatGateway\\Infrastructure\\Rpc\\RpcChatJoiner"
_PANEL_CHAT_MESSENGER = "Qu\\La\\ChatGateway\\Infrastructure\\Rpc\\ChatMessenger"
_PANEL_S_RE = re.compile(r'\["S","([A-Za-z0-9]+)"\]')


@dataclass
class LiveAgentConfig:
    base_url: str
    api_v3_key: str
    api_v1_key: str = ""
    agent_email: str = ""
    dry_run: bool = True
    auto_transfer: bool = True
    # LoginKey → panel RPC pickUpChat before post_reply (clears visitor "waiting")
    panel_accept: bool = True
    # Optional overrides for Devices keep-online (PinGo CS presence)
    agent_user_id: str = ""
    chat_department_id: str = ""

    @property
    def v3_base(self) -> str:
        return self.base_url.rstrip("/") + "/api/v3"

    @property
    def v1_base(self) -> str:
        return self.base_url.rstrip("/") + "/api"


_HARMLESS_TRANSFER_RE = re.compile(
    r"already\s+(assigned|transferred|accepted)|"
    r"same\s+agent|"
    r"is\s+already|"
    r"not\s+needed|"
    r"no\s+change",
    re.IGNORECASE,
)


class LiveAgentClient:
    def __init__(self, config: LiveAgentConfig):
        self.config = config
        # LoginKey GETs 303 → /agent/index.php; without follow_redirects, raise_for_status
        # treats 303 as failure and panel session S is never established.
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

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

    @staticmethod
    def _v1_error_text(response: httpx.Response) -> str:
        text = (response.text or "")[:500]
        try:
            body = response.json() if response.content else {}
        except Exception:
            return text
        if not isinstance(body, dict):
            return text
        resp = body.get("response") if isinstance(body.get("response"), dict) else body
        parts = [
            str(resp.get("errormessage") or resp.get("message") or "").strip(),
            str(resp.get("status") or "").strip(),
            text,
        ]
        return " ".join(p for p in parts if p)

    @classmethod
    def _is_harmless_transfer_error(cls, status_code: int, error_text: str) -> bool:
        if status_code in {200, 204}:
            return True
        if _HARMLESS_TRANSFER_RE.search(error_text or ""):
            return True
        return False

    def transfer_to_agent(
        self,
        conversation_id: str,
        agent_email: str | None = None,
    ) -> dict[str, Any]:
        """Assign/transfer a conversation to an agent via API v1 attendants.

        LiveAgent has no dedicated chat accept/join endpoint; transferring to
        ``LIVEAGENT_AGENT_EMAIL`` is the supported way to pick up a ringing chat
        before posting a reply. Requires a real API **v1** key.
        """
        api_key = (self.config.api_v1_key or "").strip()
        email = (agent_email or self.config.agent_email or "").strip()
        if self.config.dry_run:
            logger.info("DRY_RUN transfer_to_agent %s -> %s", conversation_id, email)
            return {"dry_run": True}
        if not api_key:
            raise RuntimeError(
                "LIVEAGENT_API_V1_KEY is empty; cannot transfer. "
                "API v3 keys do not work on /api/conversations/.../attendants"
            )
        if not email:
            raise RuntimeError("LIVEAGENT_AGENT_EMAIL is empty; cannot transfer conversation")

        # LA attendants PUT only reads apikey from the query string (form body alone →
        # "Api key is not found in request"). Keep apikey in form too for older servers.
        data: dict[str, Any] = {
            "apikey": api_key,
            "agentidentifier": email,
            "useridentifier": email,
        }
        url = f"{self.config.v1_base}/conversations/{conversation_id}/attendants"
        r = self._client.put(url, params={"apikey": api_key}, data=data)
        err_text = self._v1_error_text(r)
        body: dict[str, Any] = {}
        try:
            parsed = r.json() if r.content else {}
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = {}
        resp = body.get("response") if isinstance(body.get("response"), dict) else body
        api_error = str((resp or {}).get("status") or "").upper() == "ERROR"
        if r.status_code >= 400 or api_error:
            if self._is_harmless_transfer_error(r.status_code, err_text):
                logger.info(
                    "transfer_to_agent harmless conversation=%s status=%s detail=%s",
                    conversation_id,
                    r.status_code,
                    err_text[:200],
                )
                return {"skipped": True, "status_code": r.status_code, "detail": err_text[:200]}
            logger.error(
                "transfer_to_agent failed conversation=%s status=%s detail=%s",
                conversation_id,
                r.status_code,
                err_text[:500],
            )
            if r.status_code >= 400:
                r.raise_for_status()
            raise RuntimeError(f"transfer_to_agent API error: {err_text[:300]}")

        # Soft status nudge toward Answered when transfer succeeded (best-effort).
        # API status endpoint accepts A/R/C only; ignore failures.
        try:
            status_url = f"{self.config.v1_base}/conversations/{conversation_id}/status"
            status_r = self._client.put(
                status_url,
                params={"apikey": api_key},
                data={"apikey": api_key, "status": "A", "useridentifier": email},
            )
            if status_r.status_code >= 400:
                logger.info(
                    "transfer_to_agent status nudge skipped conversation=%s status=%s detail=%s",
                    conversation_id,
                    status_r.status_code,
                    self._v1_error_text(status_r)[:200],
                )
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "transfer_to_agent status nudge error conversation=%s: %s",
                conversation_id,
                exc,
            )

        logger.info(
            "transfer_to_agent ok conversation=%s agent=%s status=%s",
            conversation_id,
            email,
            r.status_code,
        )
        if isinstance(body, dict):
            body.setdefault("transferred_to", email)
            return body
        return {"status_code": r.status_code, "transferred_to": email}

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
        # Query apikey matches attendants/status; form body still works for messages POST.
        r = self._client.post(url, params={"apikey": api_key}, data=data)
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

    def panel_login(self) -> str:
        """Consume agents/{id}/login_key and return panel session token S.

        S is embedded in agent HTML pageValues after LoginKey redirect.
        Cookie A_la_sid is also set on the shared httpx client.
        """
        agent_id = self.resolve_agent_id()
        r = self._client.get(
            f"{self.config.v3_base}/agents/{agent_id}/login_key",
            headers=self._v3_headers(),
        )
        r.raise_for_status()
        try:
            payload = r.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"login_key invalid JSON: {exc}") from exc
        key = ""
        if isinstance(payload, dict):
            key = str(payload.get("login_key") or "").strip()
        elif isinstance(payload, str):
            key = payload.strip().strip('"')
        if not key:
            raise RuntimeError("login_key empty")
        # Prefer index.php (LoginKey often 303-redirects /agent/?LoginKey=… → index.php).
        base = self.config.base_url.rstrip("/")
        candidates = [
            f"{base}/agent/index.php?LoginKey={quote(key)}",
            f"{base}/agent/?LoginKey={quote(key)}",
        ]
        html = ""
        last_status = 0
        for home in candidates:
            page = self._client.get(home, headers={"Accept": "text/html"})
            last_status = page.status_code
            if page.status_code >= 400:
                continue
            html = page.text.replace('\\"', '"')
            match = _PANEL_S_RE.search(html)
            if match:
                session = match.group(1)
                logger.info(
                    "panel_login ok agent=%s S_len=%s cookies=%s via=%s",
                    agent_id,
                    len(session),
                    sorted({c.name for c in self._client.cookies.jar}),
                    home.split(base)[-1][:60],
                )
                return session
        raise RuntimeError(
            f"panel session S not found in LoginKey HTML (last_status={last_status})"
        )

    def panel_rpc(self, payload: dict[str, Any]) -> Any:
        """POST agent-panel GWT RPC body D=<json> (requires prior panel_login cookies)."""
        body = "D=" + quote(json.dumps(payload, separators=(",", ":")))
        base = self.config.base_url.rstrip("/")
        r = self._client.post(
            base + "/agent/",
            content=body.encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": base + "/agent/",
                "Origin": base,
            },
        )
        text = (r.text or "").strip()
        if r.status_code >= 400:
            logger.warning(
                "panel_rpc http=%s M=%s body=%s",
                r.status_code,
                payload.get("M"),
                text[:300],
            )
        if text.startswith("<!"):
            raise RuntimeError(f"panel_rpc returned HTML for M={payload.get('M')}")
        try:
            parsed: Any = json.loads(text) if text else None
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"panel_rpc non-JSON M={payload.get('M')}: {text[:200]}") from exc
        if isinstance(parsed, dict) and parsed.get("e"):
            raise RuntimeError(f"panel_rpc error M={payload.get('M')}: {parsed.get('e')}")
        return parsed

    @staticmethod
    def _panel_form_value(resp: Any, key: str) -> str | None:
        """Parse GWT form rows [["name","value"],["answered","Y"],...] ."""
        if not isinstance(resp, list) or len(resp) < 2:
            return None
        for row in resp[1:]:
            if isinstance(row, list) and len(row) >= 2 and str(row[0]) == key:
                return str(row[1])
        return None

    def accept_chat(self, conversation_id: str) -> dict[str, Any]:
        """Equivalent to LA popup 「回复」: ChatAnswererRpc.pickUpChat (+ joinOperator).

        Clears visitor waiting / ringing when successful (answered=Y). Does not by itself
        post a visitor-visible type-C bubble — see create_chat_answer.
        """
        if self.config.dry_run:
            logger.info("DRY_RUN accept_chat %s", conversation_id)
            return {"dry_run": True, "answered": "Y", "conversation_id": conversation_id}
        session = self.panel_login()
        pickup = self.panel_rpc(
            {
                "C": _PANEL_CHAT_ANSWERER,
                "M": "pickUpChat",
                "S": session,
                "ticketId": conversation_id,
            }
        )
        answered = self._panel_form_value(pickup, "answered")
        if str(answered or "").upper() != "Y":
            # Not ringing / already taken → visitor stays on "waiting". Do not pretend OK.
            raise RuntimeError(
                f"pickUpChat did not accept conversation={conversation_id} answered={answered}"
            )
        join: Any = None
        try:
            join = self.panel_rpc(
                {
                    "C": _PANEL_CHAT_JOINER,
                    "M": "joinOperator",
                    "S": session,
                    "cid": conversation_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "joinOperator failed conversation=%s (pickUp answered=%s): %s",
                conversation_id,
                answered,
                exc,
            )
        logger.info(
            "accept_chat conversation=%s answered=%s join=%s",
            conversation_id,
            answered,
            join,
        )
        return {
            "conversation_id": conversation_id,
            "answered": answered,
            "pickup": pickup,
            "join": join,
            "session": session,
        }

    def resolve_chat_group_id(self, conversation_id: str) -> str:
        """Return the livechat message-group id (rtype/type C) for ChatMessenger.createAnswer.

        LA panel RPC ``chatId`` is the type-C *message group* UUID, not the conversation /
        ticket id. Passing the ticket id yields a misleading 「您没有权限执行此操作」.
        """
        groups = self.get_ticket_messages(conversation_id)
        chat_groups = [
            g
            for g in groups
            if isinstance(g, dict) and str(g.get("type") or g.get("rtype") or "").upper() == "C"
        ]
        if not chat_groups:
            raise RuntimeError(f"no type-C chat message group for conversation={conversation_id}")
        # Prefer the latest C group (open/active livechat thread).
        group = chat_groups[-1]
        gid = str(group.get("id") or group.get("messagegroupid") or "").strip()
        if not gid:
            raise RuntimeError(f"type-C group missing id for conversation={conversation_id}")
        return gid

    def create_chat_answer(
        self,
        conversation_id: str,
        message: str,
        *,
        session: str | None = None,
        chat_group_id: str | None = None,
    ) -> dict[str, Any]:
        """ChatMessenger.createAnswer — visitor-visible livechat (message group type C).

        ``chatId`` must be the type-C message group id (see resolve_chat_group_id). Using the
        conversation/ticket id makes LA return 「您没有权限执行此操作」.
        """
        if self.config.dry_run:
            logger.info("DRY_RUN create_chat_answer %s -> %s", conversation_id, message[:200])
            return {"dry_run": True, "conversation_id": conversation_id, "path": "type_c"}
        sess = (session or "").strip() or self.panel_login()
        group_id = (chat_group_id or "").strip() or self.resolve_chat_group_id(conversation_id)
        resp = self.panel_rpc(
            {
                "C": _PANEL_CHAT_MESSENGER,
                "M": "createAnswer",
                "S": sess,
                "chatId": group_id,
                "text": message,
                "fileIds": "",
            }
        )
        message_id = self._panel_form_value(resp, "messageid") if isinstance(resp, list) else None
        logger.info(
            "create_chat_answer ok conversation=%s group=%s messageid=%s",
            conversation_id,
            group_id,
            message_id,
        )
        external = message_id or f"la-c-{conversation_id}"
        if isinstance(resp, dict):
            return {
                **resp,
                "path": "type_c",
                "chat_group_id": group_id,
                "external_stub": external,
            }
        return {
            "result": resp,
            "path": "type_c",
            "chat_group_id": group_id,
            "messageid": message_id,
            "external_stub": external,
        }

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

    def resolve_agent_id(self, email: str | None = None) -> str:
        """Resolve LiveAgent agent id from email (or configured override)."""
        override = (self.config.agent_user_id or "").strip()
        if override:
            return override
        target = (email or self.config.agent_email or "").strip().lower()
        if not target:
            raise RuntimeError("LIVEAGENT_AGENT_EMAIL / LIVEAGENT_AGENT_USER_ID empty; cannot resolve agent")
        r = self._client.get(
            f"{self.config.v3_base}/agents",
            headers=self._v3_headers(),
            params={"_perPage": 100},
        )
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else (data.get("data") or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_email = str(row.get("email") or row.get("mail") or "").strip().lower()
            if row_email == target:
                agent_id = str(row.get("id") or row.get("userid") or "").strip()
                if agent_id:
                    return agent_id
        raise RuntimeError(f"LiveAgent agent not found for email={target}")

    def list_devices(self, *, per_page: int = 100) -> list[dict[str, Any]]:
        r = self._client.get(
            f"{self.config.v3_base}/devices",
            headers=self._v3_headers(),
            params={"_perPage": per_page},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def list_departments(self, *, per_page: int = 100) -> list[dict[str, Any]]:
        r = self._client.get(
            f"{self.config.v3_base}/departments",
            headers=self._v3_headers(),
            params={"_perPage": per_page},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def resolve_chat_department_id(self, agent_id: str | None = None) -> str:
        """Pick chat department id: config override, else agent membership, else first dept."""
        override = (self.config.chat_department_id or "").strip()
        if override:
            return override
        depts = self.list_departments()
        aid = (agent_id or "").strip()
        for dept in depts:
            if not isinstance(dept, dict):
                continue
            dept_id = str(dept.get("department_id") or dept.get("id") or "").strip()
            if not dept_id:
                continue
            agent_ids = dept.get("agent_ids") or []
            if aid and isinstance(agent_ids, list) and aid in [str(x) for x in agent_ids]:
                return dept_id
        for dept in depts:
            if not isinstance(dept, dict):
                continue
            dept_id = str(dept.get("department_id") or dept.get("id") or "").strip()
            if dept_id:
                return dept_id
        return "default"

    @staticmethod
    def _is_chat_device(row: dict[str, Any]) -> bool:
        service = str(row.get("service_type") or "").upper()
        return service in {"T", "CHAT"}

    @staticmethod
    def _device_type_rank(row: dict[str, Any]) -> int:
        dtype = str(row.get("type") or "").upper()
        # Prefer EXTERNAL when present; PinGo 5.67.7 typically only has Web (W) chat devices.
        if dtype in {"E", "EXTERNAL"}:
            return 0
        if dtype in {"W", "WEB"}:
            return 1
        return 9

    def ensure_external_chat_device(self, agent_id: str) -> dict[str, Any]:
        """Ensure a chat device exists for the agent and return it.

        Research targeted EXTERNAL (E) devices. On PinGo 5.67.7, POST /devices only
        allows phone devices, so we reuse the existing Web (W) chat device when present
        and only attempt EXTERNAL create as a best-effort fallback.
        """
        aid = (agent_id or "").strip()
        if not aid:
            raise RuntimeError("agent_id required for ensure_external_chat_device")

        devices = self.list_devices()
        candidates = [
            d
            for d in devices
            if isinstance(d, dict)
            and str(d.get("agent_id") or d.get("userid") or d.get("user_id") or "") == aid
            and self._is_chat_device(d)
        ]
        candidates.sort(key=self._device_type_rank)
        if candidates:
            chosen = candidates[0]
            logger.info(
                "keep_online reuse chat device id=%s type=%s service_type=%s agent=%s",
                chosen.get("id"),
                chosen.get("type"),
                chosen.get("service_type"),
                aid,
            )
            return chosen

        # Best-effort create EXTERNAL chat device (often rejected: only phone creatable).
        if self.config.dry_run:
            logger.info("DRY_RUN ensure_external_chat_device create agent=%s", aid)
            return {
                "id": "dry-device",
                "agent_id": aid,
                "type": "E",
                "service_type": "T",
                "online_status": "N",
                "preset_status": "N",
                "dry_run": True,
            }
        payload = {
            "agent_id": aid,
            "type": "E",
            "service_type": "T",
            "online_status": "N",
            "preset_status": "N",
        }
        r = self._client.post(
            f"{self.config.v3_base}/devices",
            headers=self._v3_headers(),
            json=payload,
        )
        if r.status_code < 400:
            body = r.json() if r.content else {}
            if isinstance(body, dict) and body.get("id") is not None:
                logger.info("keep_online created EXTERNAL chat device id=%s agent=%s", body.get("id"), aid)
                return body
        detail = (r.text or "")[:300]
        logger.warning(
            "keep_online cannot create EXTERNAL chat device agent=%s status=%s detail=%s "
            "(PinGo may only allow phone device create; open LA panel once to seed a Web chat device)",
            aid,
            r.status_code,
            detail,
        )
        raise RuntimeError(
            f"No chat device for agent={aid} and POST /devices failed ({r.status_code}): {detail}"
        )

    def set_online(
        self,
        device_id: str | int,
        *,
        agent_id: str,
        device_type: str = "W",
        service_type: str = "T",
        online: bool = True,
    ) -> dict[str, Any]:
        """PUT /api/v3/devices/{id} presence (online_status/preset_status N or F)."""
        status = "N" if online else "F"
        payload = {
            "agent_id": agent_id,
            "type": device_type or "W",
            "service_type": service_type or "T",
            "online_status": status,
            "preset_status": status,
        }
        if self.config.dry_run:
            logger.info("DRY_RUN set_online device=%s payload=%s", device_id, payload)
            return {"dry_run": True, **payload, "id": device_id}
        r = self._client.put(
            f"{self.config.v3_base}/devices/{device_id}",
            headers=self._v3_headers(),
            json=payload,
        )
        if r.status_code >= 400:
            logger.error("set_online failed device=%s status=%s detail=%s", device_id, r.status_code, r.text[:300])
            r.raise_for_status()
        body = r.json() if r.content else {}
        return body if isinstance(body, dict) else {"id": device_id, "online_status": status}

    def set_department_chat(
        self,
        device_id: str | int,
        department_id: str,
        *,
        user_id: str,
        online: bool = True,
    ) -> dict[str, Any]:
        """PUT /api/v3/devices/{id}/departments/{departmentId} chat presence."""
        status = "N" if online else "F"
        dept = (department_id or "default").strip() or "default"
        payload = {
            "device_id": int(device_id) if str(device_id).isdigit() else device_id,
            "department_id": dept,
            "user_id": user_id,
            "online_status": status,
        }
        if self.config.dry_run:
            logger.info("DRY_RUN set_department_chat device=%s dept=%s payload=%s", device_id, dept, payload)
            return {"dry_run": True, **payload}
        r = self._client.put(
            f"{self.config.v3_base}/devices/{device_id}/departments/{dept}",
            headers=self._v3_headers(),
            json=payload,
        )
        if r.status_code >= 400:
            logger.error(
                "set_department_chat failed device=%s dept=%s status=%s detail=%s",
                device_id,
                dept,
                r.status_code,
                r.text[:300],
            )
            r.raise_for_status()
        body = r.json() if r.content else {}
        return body if isinstance(body, dict) else payload

    def get_online_status(self, agent_id: str | None = None) -> dict[str, Any]:
        """Read agent presence via v1 onlinestatus + optional v3 agent status."""
        result: dict[str, Any] = {"agents": [], "agent_status": None}
        api_key = (self.config.api_v1_key or "").strip()
        if api_key:
            r = self._client.get(
                f"{self.config.v1_base}/onlinestatus/agents",
                params={"apikey": api_key},
                headers={"Accept": "application/json"},
            )
            if r.status_code < 400:
                try:
                    body = r.json() if r.content else {}
                except Exception:
                    body = {}
                resp = body.get("response") if isinstance(body, dict) else {}
                agents = (resp or {}).get("agentsOnlineStates") if isinstance(resp, dict) else None
                if isinstance(agents, list):
                    result["agents"] = agents
                else:
                    result["raw"] = body
            else:
                logger.warning("get_online_status v1 failed status=%s detail=%s", r.status_code, r.text[:200])
        aid = (agent_id or self.config.agent_user_id or "").strip()
        if aid:
            r = self._client.get(
                f"{self.config.v3_base}/agents/{aid}/status",
                headers=self._v3_headers(),
            )
            if r.status_code < 400:
                try:
                    result["agent_status"] = r.json() if r.content else None
                except Exception:
                    result["agent_status"] = None
        return result

    @staticmethod
    def _agent_chat_online(online_status: Any) -> bool | None:
        """Return True if status includes chat online (T/N), False if offline, else None."""
        s = str(online_status or "").strip().upper()
        if not s or s == "F":
            return False
        if "T" in s or "N" in s:
            return True
        return None

    def keep_agent_online(self) -> dict[str, Any]:
        """Best-effort Devices keep-alive so visitors can start livechat.

        Does not touch auto-transfer / post_reply. Failures should be handled by caller.
        """
        agent_id = self.resolve_agent_id()
        device = self.ensure_external_chat_device(agent_id)
        device_id = device.get("id")
        if device_id is None:
            raise RuntimeError(f"chat device missing id for agent={agent_id}")
        dtype = str(device.get("type") or "W")
        stype = str(device.get("service_type") or "T")
        self.set_online(device_id, agent_id=agent_id, device_type=dtype, service_type=stype, online=True)
        dept_id = self.resolve_chat_department_id(agent_id)
        try:
            self.set_department_chat(device_id, dept_id, user_id=agent_id, online=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "keep_online department status skipped agent=%s device=%s dept=%s: %s",
                agent_id,
                device_id,
                dept_id,
                exc,
            )

        status = self.get_online_status(agent_id)
        agents = status.get("agents") or []
        mine = next((a for a in agents if isinstance(a, dict) and str(a.get("id") or "") == agent_id), None)
        online_flag = None
        online_raw = None
        if isinstance(mine, dict):
            online_raw = mine.get("onlineStatus") or mine.get("online_status")
            online_flag = self._agent_chat_online(online_raw)
        if online_flag is False:
            logger.warning(
                "keep_online agent=%s device=%s still offline after Devices PUT "
                "(onlineStatus=%r). LA panel browser session may still be required.",
                agent_id,
                device_id,
                online_raw,
            )
        else:
            logger.info(
                "keep_online ok agent=%s device=%s type=%s/%s dept=%s onlineStatus=%r",
                agent_id,
                device_id,
                dtype,
                stype,
                dept_id,
                online_raw,
            )
        return {
            "agent_id": agent_id,
            "device_id": device_id,
            "device_type": dtype,
            "service_type": stype,
            "department_id": dept_id,
            "online_status": online_raw,
            "chat_online": online_flag,
            "status": status,
        }

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
        # Collapse whitespace so LA echoes match local Smart bodies.
        body = " ".join((item.get("body") or "").strip().split())
        if known_ai_bodies and body and body in known_ai_bodies:
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
    from app.config import get_settings

    settings = get_settings()
    cfg = conn.config if isinstance(getattr(conn, "config", None), dict) else {}
    auto_transfer = cfg.get("auto_transfer")
    if auto_transfer is None:
        auto_transfer = settings.liveagent_auto_transfer
    panel_accept = cfg.get("panel_accept")
    if panel_accept is None:
        panel_accept = settings.liveagent_panel_accept
    agent_user_id = str(cfg.get("agent_user_id") or settings.liveagent_agent_user_id or "").strip()
    chat_department_id = str(
        cfg.get("chat_department_id") or settings.liveagent_chat_department_id or ""
    ).strip()
    return LiveAgentClient(
        LiveAgentConfig(
            base_url=conn.base_url,
            api_v3_key=conn.api_v3_key,
            api_v1_key=conn.api_v1_key,
            agent_email=conn.agent_email,
            dry_run=bool(conn.dry_run),
            auto_transfer=bool(auto_transfer),
            panel_accept=bool(panel_accept),
            agent_user_id=agent_user_id,
            chat_department_id=chat_department_id,
        )
    )
