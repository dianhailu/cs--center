"use client";

import { useEffect } from "react";
import { fetchMe, getStoredAgent, getStoredToken, saveSession } from "@/lib/api";

/** Refresh scopes from /auth/me so multi-product switcher stays current after deploy. */
export default function SessionBootstrap() {
  useEffect(() => {
    const token = getStoredToken();
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const me = await fetchMe(token);
        if (cancelled) return;
        const prev = getStoredAgent();
        if (!prev) return;
        saveSession({
          ...prev,
          access_token: token,
          agent_id: me.agent_id,
          email: me.email,
          name: me.name,
          role: me.role,
          workspace_id: me.workspace_id,
          workspace_name: me.workspace_name || prev.workspace_name,
          product_code: me.product_code || prev.product_code,
          country_code: me.country_code || prev.country_code,
          customer_reply_lang: me.customer_reply_lang || prev.customer_reply_lang,
          product_codes: me.product_codes || prev.product_codes,
          country_codes: me.country_codes || prev.country_codes,
          scopes: me.scopes?.length ? me.scopes : prev.scopes,
          can_edit_knowledge: me.can_edit_knowledge,
          can_manage_users: me.can_manage_users,
          can_manage_catalog: me.can_manage_catalog,
        });
        window.dispatchEvent(new Event("cs-session-updated"));
      } catch {
        /* ignore — pages handle auth errors */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
