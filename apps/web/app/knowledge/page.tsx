"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConsoleTopbar from "@/components/ConsoleTopbar";
import {
  ApiError,
  FaqItem,
  UnknownQuestion,
  getStoredToken,
  listFaq,
  listUnknowns,
  userFacingError,
  AGENT_KEY,
} from "@/lib/api";

function matchesQuery(item: FaqItem, q: string): boolean {
  if (!q) return true;
  const hay = [
    item.question.label,
    item.question.zh,
    item.question.en,
    item.question.id,
    item.answer.label,
    item.answer.zh,
    item.answer.en,
    item.answer.id,
    item.category.label,
    item.category.zh,
    item.category.en,
    item.sheet || "",
    String(item.id ?? ""),
  ]
    .join(" ")
    .toLowerCase();
  return hay.includes(q);
}

export default function KnowledgePage() {
  const router = useRouter();
  const [agentName, setAgentName] = useState("");
  const [items, setItems] = useState<FaqItem[]>([]);
  const [unknowns, setUnknowns] = useState<UnknownQuestion[]>([]);
  const [unknownTotal, setUnknownTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

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
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [faq, uq] = await Promise.all([
          listFaq(t),
          listUnknowns(t, "open"),
        ]);
        if (cancelled) return;
        setItems(faq.items || []);
        setUnknowns(uq.items || []);
        setUnknownTotal(uq.total_matching ?? uq.count ?? 0);
        setError("");
      } catch (err) {
        if (err instanceof ApiError && err.authFailed) return;
        if (!cancelled) setError(userFacingError(err, "加载知识库失败"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => matchesQuery(item, q));
  }, [items, query]);

  return (
    <div className="shell">
      <ConsoleTopbar
        subtitle={`${agentName || "Agent"} · CS-PinGo 知识库`}
      />
      <div className="kb-page">
        <div className="kb-head">
          <div>
            <h1>CS-PinGo Agent 知识库</h1>
            <p className="muted">
              浏览 FAQ 条目（只读）。AI 仍不向访客投递（AI_SEND_TO_CUSTOMER=false）。
            </p>
          </div>
          <div className="kb-stats">
            <span className="badge">{items.length} 条 FAQ</span>
            <span className="badge warn">{unknownTotal} 条待补未知问</span>
          </div>
        </div>

        <div className="kb-search">
          <input
            type="search"
            placeholder="搜索问题、答案、分类…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="搜索知识库"
          />
          <span className="muted kb-filter-count">
            {loading ? "加载中…" : `显示 ${filtered.length} / ${items.length}`}
          </span>
        </div>

        {error ? <div className="error">{error}</div> : null}

        {unknowns.length > 0 ? (
          <section className="kb-unknowns" aria-label="待补未知问题">
            <div className="kb-section-head">
              <h2>待补未知问题</h2>
              <span className="muted">最近 {unknowns.length} 条 · 只读预览</span>
            </div>
            <ul className="kb-unknown-list">
              {unknowns.map((u) => (
                <li key={u.id || `${u.date}-${u.question}`}>
                  <span className="kb-unknown-date">{u.date || "—"}</span>
                  <span className="kb-unknown-q">{u.question || "—"}</span>
                  {u.external_code ? (
                    <span className="badge neutral">{u.external_code}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="kb-list" aria-label="FAQ 列表">
          {!loading && filtered.length === 0 ? (
            <div className="empty">没有匹配的知识条目</div>
          ) : null}
          {filtered.map((item) => (
            <article key={String(item.id)} className="kb-card">
              <div className="kb-card-top">
                <span className="badge neutral">
                  {item.category.label || "未分类"}
                </span>
                {item.sheet ? (
                  <span className="muted kb-sheet">{item.sheet}</span>
                ) : null}
                <span className="muted kb-id">#{item.id}</span>
              </div>
              <h3 className="kb-q">{item.question.label || "（无问题）"}</h3>
              <p className="kb-a">{item.answer.label || "（无答案）"}</p>
              {(item.question.en || item.question.id) &&
              item.question.label !== item.question.en &&
              item.question.label !== item.question.id ? (
                <p className="kb-alt muted">
                  {item.question.en || item.question.id}
                </p>
              ) : null}
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}
