const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8080";

export type LoginResult = {
  access_token: string;
  agent_id: string;
  email: string;
  name: string;
  workspace_id: string;
  workspace_name: string;
};

export type Conversation = {
  id: string;
  external_id: string;
  external_code?: string | null;
  subject?: string | null;
  status: string;
  customer_name?: string | null;
  customer_email?: string | null;
  tags: string[];
  needs_human: boolean;
  ai_handled: boolean;
  last_message_at?: string | null;
  channel_type?: string | null;
};

export type Message = {
  id: string;
  direction: string;
  sender_type: string;
  body: string;
  send_status: string;
  created_at: string;
};

function authHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

export async function login(email: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listConversations(token: string, queue?: string): Promise<Conversation[]> {
  const q = queue ? `?queue=${encodeURIComponent(queue)}` : "";
  const res = await fetch(`${API_BASE}/api/conversations${q}`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getConversation(token: string, id: string) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<Conversation & { messages: Message[]; customer_snapshot: Record<string, unknown> }>;
}

export async function sendMessage(token: string, id: string, body: string, asNote = false) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}/messages`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ body, as_note: asNote }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function assignMe(token: string, id: string) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}/assign`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function closeConversation(token: string, id: string) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}/close`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function wsUrl(token: string) {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/ws?token=${encodeURIComponent(token)}`;
}

export { API_BASE };
