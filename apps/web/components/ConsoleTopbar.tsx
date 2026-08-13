"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { clearSession } from "@/lib/api";

type Props = {
  subtitle?: ReactNode;
  showLogout?: boolean;
};

export default function ConsoleTopbar({
  subtitle = "PinGo 客服台",
  showLogout = true,
}: Props) {
  const pathname = usePathname() || "";
  const router = useRouter();
  const livechatActive =
    pathname === "/inbox" ||
    pathname.startsWith("/inbox/") ||
    pathname === "/inbox/chat" ||
    pathname.startsWith("/inbox/chat");
  const knowledgeActive =
    pathname === "/knowledge" || pathname.startsWith("/knowledge/");
  const statsActive =
    pathname === "/stats" || pathname.startsWith("/stats/");

  function logout() {
    clearSession();
    router.replace("/login/");
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="brand-mark">
          <span className="brand-dot" aria-hidden />
          <div>
            <div className="brand">CS Midplatform</div>
            <div className="muted">{subtitle}</div>
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
        </nav>
      </div>
      {showLogout ? (
        <button className="secondary" onClick={logout} type="button">
          退出
        </button>
      ) : null}
    </header>
  );
}
