"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, login, TOKEN_KEY, AGENT_KEY } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const [email, setEmail] = useState("agent@pingo.com");
  const [password, setPassword] = useState("agent123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const reason = search.get("reason");
    if (reason) setError(reason);
  }, [search]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await login(email, password);
      localStorage.setItem(TOKEN_KEY, result.access_token);
      localStorage.setItem(AGENT_KEY, JSON.stringify(result));
      router.push("/inbox/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError(err instanceof Error ? err.message : "登录失败");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="brand-mark" style={{ marginBottom: "0.35rem" }}>
          <span className="brand-dot" aria-hidden />
          <h1 style={{ margin: 0 }}>CS Midplatform</h1>
        </div>
        <p className="muted">PinGo 印尼客服台 · LiveAgent</p>
        <label className="field">
          <span>Email</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            required
          />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </button>
        {error ? <div className="error">{error}</div> : null}
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="empty">加载中…</div>}>
      <LoginForm />
    </Suspense>
  );
}
