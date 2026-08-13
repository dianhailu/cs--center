"use client";

import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  clearSession,
  contextLabel,
  getStoredAgent,
  getStoredToken,
  LoginResult,
  saveSession,
  switchContext,
  userFacingError,
} from "@/lib/api";

type Props = {
  subtitle?: ReactNode;
  showLogout?: boolean;
};

const LANG_LABEL: Record<string, string> = {
  id: "印尼语",
  zh: "中文",
  en: "English",
};

export default function ConsoleTopbar({
  subtitle,
  showLogout = true,
}: Props) {
  const pathname = usePathname() || "";
  const router = useRouter();
  const [agent, setAgent] = useState<LoginResult | null>(null);
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    setAgent(getStoredAgent());
  }, [pathname]);

  const livechatActive =
    pathname === "/inbox" ||
    pathname.startsWith("/inbox/") ||
    pathname === "/inbox/chat" ||
    pathname.startsWith("/inbox/chat");
  const knowledgeActive =
    pathname === "/knowledge" || pathname.startsWith("/knowledge/");
  const statsActive =
    pathname === "/stats" || pathname.startsWith("/stats/");
  const adminActive =
    pathname === "/admin" || pathname.startsWith("/admin/");

  const showAdmin =
    Boolean(agent?.can_manage_users || agent?.can_manage_catalog);
  const scopes = agent?.scopes || [];
  const displaySubtitle =
    subtitle ??
    `${agent?.name || "Agent"} · ${contextLabel(agent)}`;

  function logout() {
    clearSession();
    router.replace("/login/");
  }

  async function onSwitch(workspaceId: string) {
    const token = getStoredToken();
    if (!token || workspaceId === agent?.workspace_id) return;
    setSwitching(true);
    try {
      const next = await switchContext(token, { workspace_id: workspaceId });
      saveSession(next);
      setAgent(next);
      router.refresh();
      window.location.reload();
    } catch (err) {
      alert(userFacingError(err, "切换失败"));
    } finally {
      setSwitching(false);
    }
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="brand-mark">
          <span className="brand-dot" aria-hidden />
          <div>
            <div className="brand">Smart-CS Center</div>
            <div className="muted">{displaySubtitle}</div>
          </div>
        </div>
        <nav className="console-nav" aria-label="主菜单">
          <Link
            href="/inbox/"
            className={`console-nav-link${livechatActive ? " active" : ""}`}
          >
            Livechat
          </Link>
          <Link
            href="/knowledge/"
            className={`console-nav-link${knowledgeActive ? " active" : ""}`}
          >
            知识库
          </Link>
          <Link
            href="/stats/"
            className={`console-nav-link${statsActive ? " active" : ""}`}
          >
            数据统计
          </Link>
          {showAdmin ? (
            <Link
              href="/admin/"
              className={`console-nav-link${adminActive ? " active" : ""}`}
            >
              账户与权限
            </Link>
          ) : null}
        </nav>
      </div>
      <div className="topbar-right">
        {scopes.length > 0 ? (
          <label className="context-switcher">
            <span className="sr-only">产品 / 国家</span>
            <select
              value={agent?.workspace_id || ""}
              disabled={switching || scopes.length <= 1}
              onChange={(e) => onSwitch(e.target.value)}
              aria-label="切换产品与国家"
            >
              {scopes.map((s) => (
                <option key={s.workspace_id} value={s.workspace_id}>
                  {s.product_name} · {s.country_name}
                  {s.customer_reply_lang
                    ? `（回复 ${LANG_LABEL[s.customer_reply_lang] || s.customer_reply_lang}）`
                    : ""}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {showLogout ? (
          <button className="secondary" onClick={logout} type="button">
            退出
          </button>
        ) : null}
      </div>
    </header>
  );
}
