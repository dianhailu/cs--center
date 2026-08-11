"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getStoredToken } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    const token = getStoredToken();
    router.replace(token ? "/inbox/" : "/login/");
  }, [router]);
  return <div className="empty">Loading…</div>;
}
