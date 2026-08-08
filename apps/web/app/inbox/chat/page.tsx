"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  assignMe,
  closeConversation,
  getConversation,
  Message,
  sendMessage,
  wsUrl,
} from "@/lib/api";

function ChatInner() {
  const search = useSearchParams();
  const router = useRouter();
  const id = search.get("id") || "";
  const [token, setToken] = useState("");
  const [subject, setSubject] = useState("");
  const [meta, setMeta] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh(t: string, conversationId: string) {
    const data = await getConversation(t, conversationId);
    setSubject(data.subject || data.external_code || data.external_id);
    setMeta(
      [data.customer_name, data.customer_email, data.status, data.needs_human ? "needs_human" : null]
        .filter(Boolean)
        .join(" · ")
    );
    setMessages(data.messages || []);
  }

  useEffect(() => {
    const t = localStorage.getItem("cs_token");
    if (!t) {
      router.replace("/login/");
      return;
    }
    if (!id) {
      router.replace("/inbox/");
      return;
    }
    setToken(t);
    refresh(t, id).catch((err) => setError(String(err)));
    const socket = new WebSocket(wsUrl(t));
    socket.onmessage = () => {
      refresh(t, id).catch(() => undefined);
    };
    const timer = setInterval(() => refresh(t, id).catch(() => undefined), 5000);
    return () => {
      socket.close();
      clearInterval(timer);
    };
  }, [id, router]);

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
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <div className="brand">CS Midplatform</div>
          <div className="muted">
            <Link href="/inbox/">← Back to inbox</Link>
          </div>
        </div>
      </header>
      <div className="detail">
        <div className="detail-header">
          <div>
            <h2 style={{ margin: 0, fontFamily: "var(--font)" }}>{subject}</h2>
            <div className="muted">{meta}</div>
          </div>
          <div className="actions">
            <button
              type="button"
              className="secondary"
              onClick={() => assignMe(token, id).then(() => refresh(token, id))}
            >
              Assign me
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => closeConversation(token, id).then(() => refresh(token, id))}
            >
              Close
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
            return (
              <div key={m.id} className={`bubble ${cls}`}>
                <div className="meta">
                  {m.sender_type} · {m.send_status} · {new Date(m.created_at).toLocaleString()}
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
            placeholder="Write a reply to the customer…"
          />
          <button type="submit" disabled={busy || !body.trim()}>
            {busy ? "Sending…" : "Send"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="empty">Loading…</div>}>
      <ChatInner />
    </Suspense>
  );
}
