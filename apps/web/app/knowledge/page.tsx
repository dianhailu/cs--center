"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConsoleTopbar from "@/components/ConsoleTopbar";
import {
  ApiError,
  FaqItem,
  KnowledgeCategory,
  LangTriple,
  UnknownQuestion,
  createFaq,
  createKnowledgeCategory,
  getStoredToken,
  listFaq,
  listKnowledgeCategories,
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

function firstFilledLang(q: LangTriple, a: LangTriple): "zh" | "id" | "en" {
  for (const k of ["zh", "id", "en"] as const) {
    if (q[k].trim() || a[k].trim()) return k;
  }
  return "zh";
}

function warnToast(warnings?: string[]): string {
  if (!warnings?.length) return "";
  return warnings
    .map((w) =>
      w.includes("OPENAI_API_KEY")
        ? "自动翻译未执行：服务端未配置 OPENAI_API_KEY，其他语言未更新"
        : w
    )
    .join("；");
}

function catLabel(c: KnowledgeCategory | FaqItem["category"] | undefined): string {
  if (!c) return "未分类";
  if ("slug" in c) {
    const lab = c.label;
    return lab.label || lab.zh || lab.id || lab.en || c.slug;
  }
  return c.label || c.zh || c.id || c.en || "未分类";
}

function matchesQuery(item: FaqItem, q: string): boolean {
  if (!q) return true;
  const hay = [
    item.code || "",
    item.category_slug || "",
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
  | { kind: "create"; categorySlug: string }
  | { kind: "edit"; item: FaqItem }
  | { kind: "resolve"; unknown: UnknownQuestion };

function LangFields({
  question,
  answer,
  onQuestion,
  onAnswer,
  onLangFocus,
}: {
  question: LangTriple;
  answer: LangTriple;
  onQuestion: (v: LangTriple) => void;
  onAnswer: (v: LangTriple) => void;
  onLangFocus?: (lang: "zh" | "id" | "en") => void;
}) {
  return (
    <div className="kb-form-langs">
      {LANG_META.map(({ key, label }) => (
        <div key={key} className="kb-form-lang">
          <div className="kb-lang-tag">{label}</div>
          <label className="kb-field">
            <span>问题</span>
            <textarea
              rows={2}
              value={question[key]}
              onFocus={() => onLangFocus?.(key)}
              onChange={(e) =>
                onQuestion({ ...question, [key]: e.target.value })
              }
              placeholder={`${label} question（可只填一种语言）`}
            />
          </label>
          <label className="kb-field">
            <span>答案</span>
            <textarea
              rows={4}
              value={answer[key]}
              onFocus={() => onLangFocus?.(key)}
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
  const [categories, setCategories] = useState<KnowledgeCategory[]>([]);
  const [unknowns, setUnknowns] = useState<UnknownQuestion[]>([]);
  const [unknownTotal, setUnknownTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [activeSlug, setActiveSlug] = useState<string>("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editor, setEditor] = useState<EditorMode | null>(null);
  const [formQ, setFormQ] = useState<LangTriple>(emptyTriple());
  const [formA, setFormA] = useState<LangTriple>(emptyTriple());
  const [formSlug, setFormSlug] = useState("");
  const [autoTranslate, setAutoTranslate] = useState(true);
  const [sourceLang, setSourceLang] = useState<"zh" | "id" | "en">("zh");
  const [formError, setFormError] = useState("");
  const [formWarn, setFormWarn] = useState("");
  const [toast, setToast] = useState("");
  const [showNewCat, setShowNewCat] = useState(false);
  const [newCatSlug, setNewCatSlug] = useState("");
  const [newCatLabel, setNewCatLabel] = useState("");
  const [retranslatingId, setRetranslatingId] = useState<number | null>(null);

  async function reload(t: string) {
    const [faq, cats, uq] = await Promise.all([
      listFaq(t),
      listKnowledgeCategories(t),
      listUnknowns(t, "open"),
    ]);
    setItems(faq.items || []);
    setCategories(cats.items || []);
    setUnknowns(uq.items || []);
    setUnknownTotal(uq.total_matching ?? uq.count ?? 0);
    setActiveSlug((prev) => {
      if (prev && (cats.items || []).some((c) => c.slug === prev)) return prev;
      return (cats.items || [])[0]?.slug || "";
    });
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
    return items.filter((item) => matchesQuery(item, q));
  }, [items, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, FaqItem[]>();
    for (const item of filtered) {
      const slug = item.category_slug || "uncategorized";
      if (!map.has(slug)) map.set(slug, []);
      map.get(slug)!.push(item);
    }
    for (const list of map.values()) {
      list.sort((a, b) => String(a.code || "").localeCompare(String(b.code || "")));
    }
    return map;
  }, [filtered]);

  const visibleSections = useMemo(() => {
    if (query.trim()) {
      return categories.filter((c) => (grouped.get(c.slug) || []).length > 0);
    }
    if (activeSlug) {
      const hit = categories.find((c) => c.slug === activeSlug);
      return hit ? [hit] : categories.slice(0, 1);
    }
    return categories;
  }, [categories, grouped, activeSlug, query]);

  function openCreate(slug?: string) {
    const s = slug || activeSlug || categories[0]?.slug || "pingo-taught";
    setFormQ(emptyTriple());
    setFormA(emptyTriple());
    setFormSlug(s);
    setAutoTranslate(true);
    setSourceLang("zh");
    setFormError("");
    setFormWarn("");
    setEditor({ kind: "create", categorySlug: s });
  }

  function openEdit(item: FaqItem) {
    const q = fromLangBlock(item.question);
    const a = fromLangBlock(item.answer);
    setFormQ(q);
    setFormA(a);
    setFormSlug(item.category_slug || "");
    setAutoTranslate(true);
    setSourceLang(firstFilledLang(q, a));
    setFormError("");
    setFormWarn("");
    setEditor({ kind: "edit", item });
  }

  function openResolve(u: UnknownQuestion) {
    const captured = (u.question || "").trim();
    const q = emptyTriple();
    q.zh = captured;
    q.id = captured;
    q.en = captured;
    setFormQ(q);
    const draft = fromLangBlock(u.draft_answer);
    if (hasAny(draft)) {
      setFormA(draft);
      setSourceLang(firstFilledLang(q, draft));
    } else if (u.suggested_draft) {
      const a = { zh: "", id: u.suggested_draft, en: "" };
      setFormA(a);
      setSourceLang("id");
    } else {
      setFormA(emptyTriple());
      setSourceLang("zh");
    }
    setFormSlug(activeSlug || categories[0]?.slug || "pingo-taught");
    setAutoTranslate(true);
    setFormError("");
    setFormWarn("");
    setEditor({ kind: "resolve", unknown: u });
  }

  async function submitNewCategory() {
    if (!token) return;
    const slug = newCatSlug.trim().toLowerCase();
    if (!slug) {
      setError("请填写分类 slug（如 pingo-product）");
      return;
    }
    try {
      const labelZh = newCatLabel.trim() || slug;
      await createKnowledgeCategory(token, {
        slug,
        label: { zh: labelZh, id: labelZh, en: labelZh },
      });
      await reload(token);
      setActiveSlug(slug);
      setShowNewCat(false);
      setNewCatSlug("");
      setNewCatLabel("");
      setError("");
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setError(userFacingError(err, "创建分类失败"));
    }
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
    if (!formSlug.trim()) {
      setFormError("请选择分类");
      return;
    }
    setSaving(true);
    setFormError("");
    setFormWarn("");
    try {
      const payload = {
        question: formQ,
        answer: formA,
        category_slug: formSlug.trim(),
        auto_translate: autoTranslate,
        source_lang: autoTranslate ? sourceLang : undefined,
      };
      let warnings: string[] | undefined;
      if (editor.kind === "create") {
        const res = await createFaq(token, payload);
        warnings = res.warnings;
      } else if (editor.kind === "edit") {
        const res = await updateFaq(token, String(editor.item.id), payload);
        warnings = res.warnings;
      } else {
        const id = editor.unknown.id;
        if (!id) throw new Error("missing unknown id");
        const res = await resolveUnknown(token, id, payload);
        warnings = res.warnings;
      }
      await reload(token);
      setActiveSlug(formSlug.trim());
      setEditor(null);
      const msg = warnToast(warnings);
      if (msg) {
        setToast(msg);
        setError(msg);
      } else {
        setError("");
        setToast("");
      }
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setFormError(userFacingError(err, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  async function retranslateItem(item: FaqItem, lang?: "zh" | "id" | "en") {
    if (!token) return;
    const q = fromLangBlock(item.question);
    const a = fromLangBlock(item.answer);
    const src = lang || firstFilledLang(q, a);
    if (!(q[src].trim() || a[src].trim())) {
      setToast(`重新翻译失败：${src} 语言内容为空`);
      return;
    }
    setRetranslatingId(Number(item.id));
    setToast("");
    try {
      const res = await updateFaq(token, String(item.id), {
        question: q,
        answer: a,
        category_slug: item.category_slug || undefined,
        auto_translate: true,
        source_lang: src,
      });
      await reload(token);
      const msg = warnToast(res.warnings);
      setToast(msg || `已从${LANG_META.find((l) => l.key === src)?.label || src}重新翻译并覆盖其他语言`);
      if (msg) setError(msg);
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setToast(userFacingError(err, "重新翻译失败"));
    } finally {
      setRetranslatingId(null);
    }
  }

  async function retranslateFromEditor() {
    if (!token || !editor || editor.kind === "create") return;
    if (!hasAny(formQ) || !hasAny(formA)) {
      setFormError("请至少填写一种语言的问题与答案后再重新翻译");
      return;
    }
    if (!(formQ[sourceLang].trim() || formA[sourceLang].trim())) {
      setFormError(`请先填写「${LANG_META.find((l) => l.key === sourceLang)?.label}」作为翻译源`);
      return;
    }
    setSaving(true);
    setFormError("");
    setFormWarn("");
    try {
      if (editor.kind === "edit") {
        const res = await updateFaq(token, String(editor.item.id), {
          question: formQ,
          answer: formA,
          category_slug: formSlug.trim() || undefined,
          auto_translate: true,
          source_lang: sourceLang,
        });
        const msg = warnToast(res.warnings);
        if (msg) {
          setFormWarn(msg);
          setToast(msg);
        } else if (res.item) {
          setFormQ(fromLangBlock(res.item.question));
          setFormA(fromLangBlock(res.item.answer));
          setToast("已重新翻译并覆盖其他语言");
        }
        await reload(token);
      } else {
        // resolve: preview by translating via temporary create isn't available;
        // just toggle autoTranslate + keep source — user saves to apply.
        setAutoTranslate(true);
        setFormWarn("未知问入库时会按所选源语言翻译覆盖其他语言，请点「填写答案并入库」");
      }
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setFormError(userFacingError(err, "重新翻译失败"));
    } finally {
      setSaving(false);
    }
  }

  const editorTitle =
    editor?.kind === "create"
      ? "在此分类下新增"
      : editor?.kind === "edit"
        ? `编辑 ${editor.item.code || `#${editor.item.id}`}`
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
              按分类编码（如 <code>pingo-product--01</code>）管理 FAQ。可只填一种语言并自动翻译。AI
              仍不向访客投递（AI_SEND_TO_CUSTOMER=false）。
            </p>
          </div>
          <div className="kb-stats">
            <span className="badge">{items.length} 条 FAQ</span>
            <span className="badge warn">{unknownTotal} 条待补未知问</span>
            <button type="button" className="secondary" onClick={() => setShowNewCat((v) => !v)}>
              新建分类
            </button>
            <button type="button" onClick={() => openCreate()}>
              在此分类下新增
            </button>
          </div>
        </div>

        {showNewCat ? (
          <section className="kb-editor" aria-label="新建分类">
            <div className="kb-section-head">
              <h2>新建分类</h2>
              <button
                type="button"
                className="secondary"
                onClick={() => setShowNewCat(false)}
              >
                取消
              </button>
            </div>
            <div className="kb-new-cat">
              <label className="kb-field">
                <span>slug（如 pingo-product）</span>
                <input
                  value={newCatSlug}
                  onChange={(e) => setNewCatSlug(e.target.value)}
                  placeholder="pingo-otp"
                />
              </label>
              <label className="kb-field">
                <span>显示名称</span>
                <input
                  value={newCatLabel}
                  onChange={(e) => setNewCatLabel(e.target.value)}
                  placeholder="注册/OTP"
                />
              </label>
              <button type="button" onClick={submitNewCategory}>
                创建分类
              </button>
            </div>
          </section>
        ) : null}

        <div className="kb-layout">
          <aside className="kb-sidebar" aria-label="分类">
            <div className="kb-sidebar-title">分类</div>
            <ul className="kb-cat-nav">
              {categories.map((c) => (
                <li key={c.slug}>
                  <button
                    type="button"
                    className={`kb-cat-nav-btn${activeSlug === c.slug && !query.trim() ? " active" : ""}`}
                    onClick={() => {
                      setActiveSlug(c.slug);
                      setQuery("");
                    }}
                  >
                    <span className="kb-cat-nav-label">{catLabel(c)}</span>
                    <span className="muted kb-cat-nav-meta">
                      {c.slug} · {c.count}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <div className="kb-main">
            <div className="kb-search">
              <input
                type="search"
                placeholder="搜索问题、答案、编码（三语均可）…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="搜索知识库"
              />
              <span className="muted kb-filter-count">
                {loading
                  ? "加载中…"
                  : `显示 ${filtered.length} / ${items.length}`}
              </span>
            </div>

            {error ? <div className="error">{error}</div> : null}
            {toast ? (
              <div className="kb-toast" role="status">
                {toast}
                <button
                  type="button"
                  className="secondary kb-inline-btn"
                  onClick={() => setToast("")}
                >
                  关闭
                </button>
              </div>
            ) : null}

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
                <div className="kb-editor-meta">
                  <label className="kb-field">
                    <span>分类</span>
                    <select
                      value={formSlug}
                      onChange={(e) => setFormSlug(e.target.value)}
                    >
                      {categories.map((c) => (
                        <option key={c.slug} value={c.slug}>
                          {catLabel(c)} ({c.slug})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="kb-check">
                    <input
                      type="checkbox"
                      checked={autoTranslate}
                      onChange={(e) => setAutoTranslate(e.target.checked)}
                    />
                    自动翻译其他语言
                  </label>
                  {autoTranslate ? (
                    <label className="kb-field">
                      <span>以哪种语言为准</span>
                      <select
                        value={sourceLang}
                        onChange={(e) =>
                          setSourceLang(e.target.value as "zh" | "id" | "en")
                        }
                      >
                        {LANG_META.map(({ key, label }) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                </div>
                <LangFields
                  question={formQ}
                  answer={formA}
                  onQuestion={setFormQ}
                  onAnswer={setFormA}
                  onLangFocus={(lang) => {
                    if (autoTranslate) setSourceLang(lang);
                  }}
                />
                {formError ? <div className="error">{formError}</div> : null}
                {formWarn ? <div className="error">{formWarn}</div> : null}
                <div className="kb-editor-actions">
                  <button type="button" onClick={submitEditor} disabled={saving}>
                    {saving
                      ? "保存中…"
                      : editor.kind === "resolve"
                        ? "填写答案并入库"
                        : "保存"}
                  </button>
                  {editor.kind === "edit" ? (
                    <button
                      type="button"
                      className="secondary"
                      onClick={retranslateFromEditor}
                      disabled={saving}
                    >
                      重新翻译
                    </button>
                  ) : null}
                </div>
              </section>
            ) : null}

            {unknowns.length > 0 ? (
              <section className="kb-unknowns" aria-label="待补未知问题">
                <div className="kb-section-head">
                  <h2>待补未知问题</h2>
                  <span className="muted">
                    最近 {unknowns.length} 条 · 可填写答案入库
                  </span>
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

            {!loading && filtered.length === 0 ? (
              <div className="empty">没有匹配的知识条目</div>
            ) : null}

            {visibleSections.map((cat) => {
              const list = grouped.get(cat.slug) || [];
              if (query.trim() && list.length === 0) return null;
              return (
                <section
                  key={cat.slug}
                  className="kb-cat-section"
                  aria-label={catLabel(cat)}
                >
                  <div className="kb-section-head">
                    <h2>
                      {catLabel(cat)}{" "}
                      <span className="muted kb-cat-slug">{cat.slug}</span>
                    </h2>
                    <button
                      type="button"
                      className="secondary kb-inline-btn"
                      onClick={() => openCreate(cat.slug)}
                    >
                      在此分类下新增
                    </button>
                  </div>
                  <div className="kb-list">
                    {list.length === 0 ? (
                      <div className="empty">此分类暂无条目</div>
                    ) : null}
                    {list.map((item) => (
                      <article key={String(item.id)} className="kb-card">
                        <div className="kb-card-top">
                          <span className="badge">{item.code || "—"}</span>
                          <span className="muted kb-id">#{item.id}</span>
                          <button
                            type="button"
                            className="secondary kb-inline-btn"
                            onClick={() => openEdit(item)}
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            className="secondary kb-inline-btn"
                            disabled={retranslatingId === Number(item.id)}
                            onClick={() => retranslateItem(item)}
                            title="按当前已填语言重新翻译并覆盖其他语言"
                          >
                            {retranslatingId === Number(item.id)
                              ? "翻译中…"
                              : "重新翻译"}
                          </button>
                        </div>
                        <MultilangBlocks
                          question={item.question}
                          answer={item.answer}
                        />
                      </article>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
