"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConsoleTopbar from "@/components/ConsoleTopbar";
import {
  ApiError,
  FaqItem,
  LangTriple,
  UnknownQuestion,
  createFaq,
  getStoredToken,
  listFaq,
  listUnknowns,
  resolveUnknown,
  updateFaq,
  userFacingError,
  AGENT_KEY,
} from "@/lib/api";

const LANG_META = [
  { key: "zh" as const, label: "中文" },
  { key: "id" as const, label: "Bahasa Indonesia" },
  { key: "en" as const, label: "English" },
];

function emptyTriple(): LangTriple {
  return { zh: "", id: "", en: "" };
}

function fromLangBlock(block?: {
  zh?: string;
  id?: string;
  en?: string;
} | null): LangTriple {
  return {
    zh: block?.zh || "",
    id: block?.id || "",
    en: block?.en || "",
  };
}

function hasAny(t: LangTriple): boolean {
  return Boolean(t.zh.trim() || t.id.trim() || t.en.trim());
}

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

type EditorMode =
  | { kind: "create" }
  | { kind: "edit"; item: FaqItem }
  | { kind: "resolve"; unknown: UnknownQuestion };

function LangFields({
  question,
  answer,
  category,
  onQuestion,
  onAnswer,
  onCategory,
  showCategory,
}: {
  question: LangTriple;
  answer: LangTriple;
  category: LangTriple;
  onQuestion: (v: LangTriple) => void;
  onAnswer: (v: LangTriple) => void;
  onCategory: (v: LangTriple) => void;
  showCategory?: boolean;
}) {
  return (
    <div className="kb-form-langs">
      {LANG_META.map(({ key, label }) => (
        <div key={key} className="kb-form-lang">
          <div className="kb-lang-tag">{label}</div>
          {showCategory ? (
            <label className="kb-field">
              <span>分类</span>
              <input
                value={category[key]}
                onChange={(e) =>
                  onCategory({ ...category, [key]: e.target.value })
                }
                placeholder={`${label} category`}
              />
            </label>
          ) : null}
          <label className="kb-field">
            <span>问题</span>
            <textarea
              rows={2}
              value={question[key]}
              onChange={(e) =>
                onQuestion({ ...question, [key]: e.target.value })
              }
              placeholder={`${label} question`}
            />
          </label>
          <label className="kb-field">
            <span>答案</span>
            <textarea
              rows={4}
              value={answer[key]}
              onChange={(e) => onAnswer({ ...answer, [key]: e.target.value })}
              placeholder={`${label} answer`}
            />
          </label>
        </div>
      ))}
    </div>
  );
}

function MultilangBlocks({
  question,
  answer,
}: {
  question: { zh?: string; id?: string; en?: string };
  answer: { zh?: string; id?: string; en?: string };
}) {
  return (
    <div className="kb-langs">
      {LANG_META.map(({ key, label }) => (
        <div key={key} className="kb-lang-block">
          <div className="kb-lang-tag">{label}</div>
          <h3 className="kb-q">{question[key]?.trim() || "（无问题）"}</h3>
          <p className="kb-a">{answer[key]?.trim() || "（无答案）"}</p>
        </div>
      ))}
    </div>
  );
}

export default function KnowledgePage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [agentName, setAgentName] = useState("");
  const [items, setItems] = useState<FaqItem[]>([]);
  const [unknowns, setUnknowns] = useState<UnknownQuestion[]>([]);
  const [unknownTotal, setUnknownTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editor, setEditor] = useState<EditorMode | null>(null);
  const [formQ, setFormQ] = useState<LangTriple>(emptyTriple());
  const [formA, setFormA] = useState<LangTriple>(emptyTriple());
  const [formCat, setFormCat] = useState<LangTriple>(emptyTriple());
  const [formError, setFormError] = useState("");

  async function reload(t: string) {
    const [faq, uq] = await Promise.all([listFaq(t), listUnknowns(t, "open")]);
    setItems(faq.items || []);
    setUnknowns(uq.items || []);
    setUnknownTotal(uq.total_matching ?? uq.count ?? 0);
  }

  useEffect(() => {
    const t = getStoredToken();
    const agent = localStorage.getItem(AGENT_KEY);
    if (!t) {
      router.replace("/login/");
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
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await reload(t);
        if (!cancelled) setError("");
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

  function openCreate() {
    setFormQ(emptyTriple());
    setFormA(emptyTriple());
    setFormCat({ zh: "已教答", id: "Diajarkan", en: "Taught" });
    setFormError("");
    setEditor({ kind: "create" });
  }

  function openEdit(item: FaqItem) {
    setFormQ(fromLangBlock(item.question));
    setFormA(fromLangBlock(item.answer));
    setFormCat(fromLangBlock(item.category));
    setFormError("");
    setEditor({ kind: "edit", item });
  }

  function openResolve(u: UnknownQuestion) {
    const captured = (u.question || "").trim();
    const q = emptyTriple();
    // Seed captured question into all question slots for easy editing
    q.zh = captured;
    q.id = captured;
    q.en = captured;
    setFormQ(q);
    const draft = fromLangBlock(u.draft_answer);
    if (hasAny(draft)) {
      setFormA(draft);
    } else if (u.suggested_draft) {
      setFormA({ zh: "", id: u.suggested_draft, en: "" });
    } else {
      setFormA(emptyTriple());
    }
    setFormCat({ zh: "已教答", id: "Diajarkan", en: "Taught" });
    setFormError("");
    setEditor({ kind: "resolve", unknown: u });
  }

  async function submitEditor() {
    if (!token || !editor) return;
    if (!hasAny(formQ)) {
      setFormError("请至少填写一种语言的问题");
      return;
    }
    if (!hasAny(formA)) {
      setFormError("请至少填写一种语言的答案");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      const payload = {
        question: formQ,
        answer: formA,
        category: formCat,
      };
      if (editor.kind === "create") {
        await createFaq(token, payload);
      } else if (editor.kind === "edit") {
        await updateFaq(token, String(editor.item.id), payload);
      } else {
        const id = editor.unknown.id;
        if (!id) throw new Error("missing unknown id");
        await resolveUnknown(token, id, payload);
      }
      await reload(token);
      setEditor(null);
      setError("");
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setFormError(userFacingError(err, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  const editorTitle =
    editor?.kind === "create"
      ? "新增 FAQ"
      : editor?.kind === "edit"
        ? `编辑 FAQ #${editor.item.id}`
        : editor?.kind === "resolve"
          ? "填写答案并入库"
          : "";

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
              每条同时展示中文 / Bahasa Indonesia / English（无语言切换）。可新增、编辑
              FAQ，并对待补未知问题填写三语答案入库。AI 仍不向访客投递（AI_SEND_TO_CUSTOMER=false）。
            </p>
          </div>
          <div className="kb-stats">
            <span className="badge">{items.length} 条 FAQ</span>
            <span className="badge warn">{unknownTotal} 条待补未知问</span>
            <button type="button" onClick={openCreate}>
              新增 FAQ
            </button>
          </div>
        </div>

        <div className="kb-search">
          <input
            type="search"
            placeholder="搜索问题、答案、分类（三语均可）…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="搜索知识库"
          />
          <span className="muted kb-filter-count">
            {loading ? "加载中…" : `显示 ${filtered.length} / ${items.length}`}
          </span>
        </div>

        {error ? <div className="error">{error}</div> : null}

        {editor ? (
          <section className="kb-editor" aria-label={editorTitle}>
            <div className="kb-section-head">
              <h2>{editorTitle}</h2>
              <button
                type="button"
                className="secondary"
                onClick={() => setEditor(null)}
                disabled={saving}
              >
                取消
              </button>
            </div>
            {editor.kind === "resolve" ? (
              <p className="muted kb-editor-hint">
                未知问（{editor.unknown.date || "—"}）：
                {editor.unknown.question || "—"}
              </p>
            ) : null}
            <LangFields
              question={formQ}
              answer={formA}
              category={formCat}
              onQuestion={setFormQ}
              onAnswer={setFormA}
              onCategory={setFormCat}
              showCategory
            />
            {formError ? <div className="error">{formError}</div> : null}
            <div className="kb-editor-actions">
              <button type="button" onClick={submitEditor} disabled={saving}>
                {saving
                  ? "保存中…"
                  : editor.kind === "resolve"
                    ? "填写答案并入库"
                    : "保存"}
              </button>
            </div>
          </section>
        ) : null}

        {unknowns.length > 0 ? (
          <section className="kb-unknowns" aria-label="待补未知问题">
            <div className="kb-section-head">
              <h2>待补未知问题</h2>
              <span className="muted">最近 {unknowns.length} 条 · 可填写三语答案入库</span>
            </div>
            <ul className="kb-unknown-list">
              {unknowns.map((u) => (
                <li key={u.id || `${u.date}-${u.question}`}>
                  <span className="kb-unknown-date">{u.date || "—"}</span>
                  <span className="kb-unknown-q">{u.question || "—"}</span>
                  {u.external_code ? (
                    <span className="badge neutral">{u.external_code}</span>
                  ) : null}
                  <button
                    type="button"
                    className="secondary kb-inline-btn"
                    onClick={() => openResolve(u)}
                  >
                    填写答案并入库
                  </button>
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
                  {item.category.label ||
                    item.category.zh ||
                    item.category.id ||
                    item.category.en ||
                    "未分类"}
                </span>
                {item.sheet ? (
                  <span className="muted kb-sheet">{item.sheet}</span>
                ) : null}
                <span className="muted kb-id">#{item.id}</span>
                <button
                  type="button"
                  className="secondary kb-inline-btn"
                  onClick={() => openEdit(item)}
                >
                  编辑
                </button>
              </div>
              <MultilangBlocks question={item.question} answer={item.answer} />
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}
