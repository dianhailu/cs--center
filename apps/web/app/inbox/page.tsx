"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConsoleTopbar from "@/components/ConsoleTopbar";
import {
  ApiError,
  Conversation,
  getStoredAgent,
  getStoredToken,
  listConversations,
  saveSession,
  switchContext,
  userFacingError,
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
  const [role, setRole] = useState("");
  const [scopesCount, setScopesCount] = useState(0);
  const [productFilter, setProductFilter] = useState<string>("all");
  const [queue, setQueue] = useState("human");
  const [searchInput, setSearchInput] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [items, setItems] = useState<Conversation[]>([]);
  const [error, setError] = useState("");
  const [openingId, setOpeningId] = useState<string | null>(null);

  const isSystemAdmin = role === "system_admin";
  const showProductFilter = isSystemAdmin && scopesCount > 1;

  useEffect(() => {
    const t = window.setTimeout(() => setSearchQ(searchInput.trim()), 280);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  const syncAgent = useCallback(() => {
    const agent = getStoredAgent();
    setRole(agent?.role || "");
    setScopesCount(agent?.scopes?.length || 0);
  }, []);

  useEffect(() => {
    syncAgent();
    window.addEventListener("cs-session-updated", syncAgent);
    return () => window.removeEventListener("cs-session-updated", syncAgent);
  }, [syncAgent]);

  const load = useMemo(
    () =>
      async (t: string, q: string, search: string, filter: string, admin: boolean) => {
        try {
          const opts =
            admin && filter === "all"
              ? { allProducts: true }
              : admin && filter
                ? { allProducts: true, productCode: filter }
                : undefined;
          const data = await listConversations(t, q || undefined, search || undefined, opts);
          setItems(data);
          setError("");
        } catch (err) {
          if (err instanceof ApiError && err.authFailed) return;
          setError(userFacingError(err, "加载失败"));
        }
      },
    []
  );

  useEffect(() => {
    const t = getStoredToken();
    if (!t) {
      router.replace("/login/");
      return;
    }
    const agent = getStoredAgent();
    const admin = agent?.role === "system_admin";
    load(t, queue, searchQ, productFilter, admin);
    const socket = new WebSocket(wsUrl(t));
    const refresh = () => load(t, queue, searchQ, productFilter, admin);
    socket.onmessage = refresh;
    const timer = setInterval(refresh, 8000);
    return () => {
      socket.close();
      clearInterval(timer);
    };
  }, [load, queue, searchQ, productFilter, router]);

  async function openConversation(c: Conversation) {
    const token = getStoredToken();
    if (!token) {
      router.replace("/login/");
      return;
    }
    setOpeningId(c.id);
    try {
      const agent = getStoredAgent();
      if (c.workspace_id && agent?.workspace_id && c.workspace_id !== agent.workspace_id) {
        const next = await switchContext(token, { workspace_id: c.workspace_id });
        saveSession(next);
      }
      router.push(`/inbox/chat/?id=${encodeURIComponent(c.id)}`);
    } catch (err) {
      alert(userFacingError(err, "打开会话失败"));
    } finally {
      setOpeningId(null);
    }
  }

  return (
    <div className="shell">
      <ConsoleTopbar />
      <div className="workspace">
        <aside className="queue">
          <div className="queue-head">
            <h1>收件箱</h1>
            <span className="queue-count">{items.length} 会话</span>
          </div>
          {showProductFilter ? (
            <div className="inbox-product-filter tabs">
              <button
                type="button"
                className={productFilter === "all" ? "active" : ""}
                onClick={() => setProductFilter("all")}
              >
                全部产品
              </button>
              <button
                type="button"
                className={productFilter === "pingo" ? "active" : ""}
                onClick={() => setProductFilter("pingo")}
              >
                PinGo
              </button>
              <button
                type="button"
                className={productFilter === "avantee" ? "active" : ""}
                onClick={() => setProductFilter("avantee")}
              >
                Avantee
              </button>
            </div>
          ) : null}
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
            <button
              key={c.id}
              type="button"
              className="conv-item conv-item-btn"
              disabled={openingId === c.id}
              onClick={() => openConversation(c)}
            >
              <div className="conv-top">
                <span className="conv-code">{ticketTitle(c)}</span>
                <span className="conv-time">{shortTime(c.last_message_at)}</span>
              </div>
              {c.product_name ? (
                <span className={`product-badge product-badge-${c.product_code || "other"}`}>
                  {c.product_name}
                </span>
              ) : null}
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
            </button>
          ))}
        </aside>
        <main className="pane-placeholder">
          <div>
            <strong>选择左侧会话</strong>
            <div className="muted">
              {showProductFilter
                ? "管理员可查看全部产品；顶部 Tab 切换知识库/统计上下文"
                : "顶部切换 PinGo / Avantee 后查看对应产品会话"}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
