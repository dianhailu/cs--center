/** LiveAgent / inbox display helpers */

export function ticketTitle(c: {
  external_code?: string | null;
  external_id: string;
}): string {
  return (c.external_code || c.external_id || "").trim() || "—";
}

export function channelLabel(ch?: string | null): string {
  if (!ch) return "—";
  const u = ch.trim().toUpperCase();
  if (u === "B") return "Chat";
  return u;
}

export function customerLine(parts: {
  name?: string | null;
  email?: string | null;
  phone?: string | null;
}): string {
  return [parts.name, parts.email, parts.phone].filter(Boolean).join(" · ") || "未知客户";
}

export function shortTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export async function copyText(text: string): Promise<boolean> {
  const v = (text || "").trim();
  if (!v || v === "—") return false;
  try {
    await navigator.clipboard.writeText(v);
    return true;
  } catch {
    return false;
  }
}
