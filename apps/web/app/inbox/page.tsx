"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Conversation, listConversations, wsUrl } from "@/lib/api";

const QUEUES = [
  { id: "human", label: "Human queue" },
  { id: "", label: "All open" },
  { id: "mine", label: "Mine" },
  { id: "closed", label: "Closed" },
];

export default function InboxPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [agentName, setAgentName] = useState("");
  const [queue, setQueue] = useState("human");
  const [items, setItems] = useState<Conversation[]>([]);
  const [error, setError] = useState("");

  const load = useMemo(
    () => async (t: string, q: string) => {
      try {
        const data = await listConversations(t, q || undefined);
        setItems(data);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Load failed");
      }
    },
    []
  );

  useEffect(() => {
    const t = localStorage.getItem("cs_token");
    const agent = localStorage.getItem("cs_agent");
    if (!t) {
      router.replace("/login");
      return;
    }
    setToken(t);
    if (agent) {
      try {
        setAgentName(JSON.parse(agent).name || "");
      } catch {
        /* ignore */
      }
    }
    load(t, queue);
    const socket = new WebSocket(wsUrl(t));
    socket.onmessage = () => load(t, queue);
    const timer = setInterval(() => load(t, queue), 8000);
    return () => {
      socket.close();
      clearInterval(timer);
    };
  }, [load, queue, router]);

  function logout() {
    localStorage.removeItem("cs_token");
    localStorage.removeItem("cs_agent");
    router.replace("/login");
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <div className="brand">CS Midplatform</div>
          <div className="muted">{agentName || "Agent"} · PinGo ID</div>
        </div>
        <button className="secondary" onClick={logout} type="button">
          Logout
        </button>
      </header>
      <div className="workspace">
        <aside className="queue">
          <div className="tabs">
            {QUEUES.map((q) => (
              <button
                key={q.id || "all"}
                type="button"
                className={queue === q.id ? "active" : ""}
                onClick={() => setQueue(q.id)}
              >
                {q.label}
              </button>
            ))}
          </div>
          {error ? <div className="error">{error}</div> : null}
          {items.length === 0 ? <div className="empty">No conversations</div> : null}
          {items.map((c) => (
            <Link key={c.id} href={`/inbox/chat/?id=${encodeURIComponent(c.id)}`} className="conv-item">
              <strong>{c.subject || c.external_code || c.external_id}</strong>
              <div className="muted">{c.customer_name || c.customer_email || "Unknown customer"}</div>
              <div style={{ marginTop: 6 }}>
                <span className="badge">{c.status}</span>
                {c.needs_human ? <span className="badge warn">needs human</span> : null}
                {c.ai_handled ? <span className="badge">ai</span> : null}
              </div>
            </Link>
          ))}
        </aside>
        <main className="empty">Select a conversation from the queue</main>
      </div>
    </div>
  );
}
