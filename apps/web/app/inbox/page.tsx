"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConsoleTopbar from "@/components/ConsoleTopbar";
import {
  ApiError,
  Conversation,
  getStoredToken,
  listConversations,
  userFacingError,
  AGENT_KEY,
  wsUrl,
} from "@/lib/api";
import { channelLabel, customerLine, shortTime, ticketTitle } from "@/lib/display";

const QUEUES = [
  { id: "human", label: "待人工" },
  { id: "", label: "全部开放" },
  { id: "mine", label: "我的" },
  { id: "closed", label: "已关闭" },
];

export default function InboxPage() {
  const router = useRouter();
  const [agentName, setAgentName] = useState("");
  const [queue, setQueue] = useState("human");
  const [searchInput, setSearchInput] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [items, setItems] = useState<Conversation[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const t = window.setTimeout(() => setSearchQ(searchInput.trim()), 280);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  const load = useMemo(
    () => async (t: string, q: string, search: string) => {
      try {
        const data = await listConversations(t, q || undefined, search || undefined);
        setItems(data);
        setError("");
      } catch (err) {
        if (err instanceof ApiError && err.authFailed) {
          // forceLogout already redirected
          return;
        }
        setError(userFacingError(err, "加载失败"));
      }
    },
    []
  );

  useEffect(() => {
    const t = getStoredToken();
    const agent = localStorage.getItem(AGENT_KEY);
    if (!t) {
      router.replace("/login/");
      return;
    }
    if (agent) {
      try {
        setAgentName(JSON.parse(agent).name || "");
      } catch {
        /* ignore */
      }
    }
    load(t, queue, searchQ);
    const socket = new WebSocket(wsUrl(t));
    socket.onmessage = () => load(t, queue, searchQ);
    const timer = setInterval(() => load(t, queue, searchQ), 8000);
    return () => {
      socket.close();
      clearInterval(timer);
    };
  }, [load, queue, searchQ, router]);

  return (
    <div className="shell">
      <ConsoleTopbar />
      <div className="workspace">
        <aside className="queue">
          <div className="queue-head">
            <h1>收件箱</h1>
            <span className="queue-count">{items.length} 会话</span>
          </div>
          <div className="inbox-search">
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="手机号 / 邮箱 / 工单号"
              aria-label="搜索会话"
              autoComplete="off"
              spellCheck={false}
            />
          </div>
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
          {items.length === 0 && !error ? (
            <div className="empty">{searchQ ? "无匹配会话" : "暂无会话"}</div>
          ) : null}
          {items.map((c) => (
            <Link
              key={c.id}
              href={`/inbox/chat/?id=${encodeURIComponent(c.id)}`}
              className="conv-item"
            >
              <div className="conv-top">
                <span className="conv-code">{ticketTitle(c)}</span>
                <span className="conv-time">{shortTime(c.last_message_at)}</span>
              </div>
              <div className="conv-customer">
                {customerLine({
                  name: c.customer_name,
                  email: c.customer_email,
                })}
              </div>
              <div className="id-strip" aria-label="LiveAgent IDs">
                <span title="会话ID">Conv {c.external_id}</span>
                <span className="sep">·</span>
                <span title="渠道">{channelLabel(c.channel_type)}</span>
                {c.la_status ? (
                  <>
                    <span className="sep">·</span>
                    <span title="LA status">{c.la_status}</span>
                  </>
                ) : null}
              </div>
              <div className="conv-flags">
                <span className="badge status">{c.status}</span>
                {c.needs_human ? <span className="badge warn">待人工</span> : null}
                {c.ai_handled ? <span className="badge">Smart</span> : null}
              </div>
            </Link>
          ))}
        </aside>
        <main className="pane-placeholder">
          <div>
            <strong>选择左侧会话</strong>
            <div className="muted">工单号优先展示 · LiveAgent 会话在此接入 PinGo 坐席</div>
          </div>
        </main>
      </div>
    </div>
  );
}
