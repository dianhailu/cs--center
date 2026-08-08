"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    const token = localStorage.getItem("cs_token");
    router.replace(token ? "/inbox" : "/login");
  }, [router]);
  return <div className="empty">Loading…</div>;
}
