"use client";

import Link from "next/link";
import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ApiError,
  assignMe,
  closeConversation,
  ConversationDetail,
  getConversation,
  getStoredToken,
  Message,
  sendMessage,
  userFacingError,
  wsUrl,
} from "@/lib/api";
import {
  channelLabel,
  copyText,
  customerLine,
  ticketTitle,
} from "@/lib/display";

function IdChip({
  label,
  value,
}: {
  label: string;
  value?: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const display = (value || "").trim() || "—";
  const canCopy = display !== "—";

  return (
    <button
      type="button"
      className={`id-chip${copied ? " copied" : ""}`}
      title={canCopy ? `复制 ${label}` : undefined}
      disabled={!canCopy}
      onClick={async () => {
        if (!canCopy) return;
        const ok = await copyText(display);
        if (ok) {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        }
      }}
    >
      <span className="lbl">{label}</span>
      <span className="val">{copied ? "已复制" : display}</span>
    </button>
  );
}

function ChatInner() {
  const search = useSearchParams();
  const router = useRouter();
  const id = search.get("id") || "";
  const [token, setToken] = useState("");
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (t: string, conversationId: string) => {
    const data = await getConversation(t, conversationId);
    setDetail(data);
    setMessages(data.messages || []);
  }, []);

  useEffect(() => {
    const t = getStoredToken();
    if (!t) {
      router.replace("/login/");
      return;
    }
    if (!id) {
      router.replace("/inbox/");
      return;
    }
    setToken(t);
    refresh(t, id).catch((err) => {
      if (err instanceof ApiError && err.authFailed) return;
      setError(userFacingError(err, "加载失败"));
    });
    const socket = new WebSocket(wsUrl(t));
    socket.onmessage = () => {
      refresh(t, id).catch(() => undefined);
    };
    const timer = setInterval(() => refresh(t, id).catch(() => undefined), 5000);
    return () => {
      socket.close();
      clearInterval(timer);
    };
  }, [id, refresh, router]);

  async function onSend(e: FormEvent) {
    e.preventDefault();
    if (!body.trim() || !id) return;
    setBusy(true);
    setError("");
    try {
      await sendMessage(token, id, body.trim());
      setBody("");
      await refresh(token, id);
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setError(userFacingError(err, "发送失败"));
    } finally {
      setBusy(false);
    }
  }

  const snap = detail?.customer_snapshot || {};
  const phone =
    (typeof snap.phone === "string" && snap.phone) ||
    null;
  const contactId =
    (typeof snap.owner_contactid === "string" && snap.owner_contactid) ||
    null;
  const title = detail ? ticketTitle(detail) : "…";

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand-mark">
          <span className="brand-dot" aria-hidden />
          <div>
            <div className="brand">CS Midplatform</div>
            <div className="muted">
              <Link href="/inbox/">← 返回收件箱</Link>
            </div>
          </div>
        </div>
      </header>
      <div className="detail">
        <div className="detail-header">
          <div style={{ minWidth: 0, flex: 1 }}>
            <h2 className="detail-title">{title}</h2>
            <div className="detail-customer">
              {detail
                ? customerLine({
                    name: detail.customer_name || (snap.owner_name as string | null),
                    email: detail.customer_email || (snap.owner_email as string | null),
                    phone,
                  })
                : "加载中…"}
            </div>
            <div className="id-row">
              <IdChip label="工单号" value={detail?.external_code || detail?.external_id} />
              <IdChip label="会话ID" value={detail?.external_id} />
              <IdChip label="联系人" value={contactId} />
              <IdChip label="渠道" value={channelLabel(detail?.channel_type)} />
              <IdChip label="LA状态" value={detail?.la_status} />
              {detail?.status ? (
                <span className="badge status" style={{ alignSelf: "center" }}>
                  {detail.status}
                </span>
              ) : null}
              {detail?.needs_human ? (
                <span className="badge warn" style={{ alignSelf: "center" }}>
                  待人工
                </span>
              ) : null}
            </div>
          </div>
          <div className="actions">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                assignMe(token, id)
                  .then(() => refresh(token, id))
                  .catch((err) => {
                    if (err instanceof ApiError && err.authFailed) return;
                    setError(userFacingError(err, "分配失败"));
                  })
              }
            >
              分配给我
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() =>
                closeConversation(token, id)
                  .then(() => refresh(token, id))
                  .catch((err) => {
                    if (err instanceof ApiError && err.authFailed) return;
                    setError(userFacingError(err, "关闭失败"));
                  })
              }
            >
              关闭
            </button>
          </div>
        </div>
        <div className="messages">
          {messages.map((m) => {
            const cls =
              m.direction === "note"
                ? "note"
                : m.sender_type === "customer"
                  ? "customer"
                  : m.sender_type === "ai"
                    ? "ai"
                    : "agent";
            const roleLabel =
              m.sender_type === "customer"
                ? "客户"
                : m.sender_type === "ai"
                  ? "Smart"
                  : m.sender_type === "agent"
                    ? "PinGo CS"
                    : m.sender_type === "system"
                      ? "系统"
                      : m.sender_type;
            return (
              <div key={m.id} className={`bubble ${cls}`}>
                <div className="meta">
                  <span className="role">{roleLabel}</span>
                  <span>·</span>
                  <span>{m.send_status}</span>
                  <span>·</span>
                  <span>{new Date(m.created_at).toLocaleString()}</span>
                </div>
                {m.body}
              </div>
            );
          })}
          {error ? <div className="error">{error}</div> : null}
        </div>
        <form className="composer" onSubmit={onSend}>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="回复客户…"
            rows={3}
          />
          <button type="submit" disabled={busy || !body.trim()}>
            {busy ? "发送中…" : "发送"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="empty">加载中…</div>}>
      <ChatInner />
    </Suspense>
  );
}
