const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8080";

const TOKEN_KEY = "cs_token";
const AGENT_KEY = "cs_agent";

export type LoginResult = {
  access_token: string;
  agent_id: string;
  email: string;
  name: string;
  workspace_id: string;
  workspace_name: string;
};

export type CustomerSnapshot = {
  owner_contactid?: string | null;
  owner_email?: string | null;
  owner_name?: string | null;
  departmentid?: string | null;
  la_status?: string | null;
  phone?: string | null;
  visitor_userid?: string | null;
  [key: string]: unknown;
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
  la_status?: string | null;
};

export type ConversationDetail = Conversation & {
  messages: Message[];
  customer_snapshot: CustomerSnapshot;
};

export type Message = {
  id: string;
  direction: string;
  sender_type: string;
  body: string;
  send_status: string;
  created_at: string;
  external_id?: string | null;
};

export class ApiError extends Error {
  status: number;
  detail: string;
  authFailed: boolean;

  constructor(status: number, detail: string, authFailed = false) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.authFailed = authFailed;
  }
}

export function clearSession() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(AGENT_KEY);
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/** Clear session and send user to login when the API rejects the JWT. */
export function forceLogout(message = "登录已失效，请重新登录") {
  clearSession();
  if (typeof window === "undefined") return;
  const q = encodeURIComponent(message);
  const target = `/login/?reason=${q}`;
  if (!window.location.pathname.startsWith("/login")) {
    window.location.replace(target);
  }
}

function authHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

function parseDetail(raw: string): string {
  const text = (raw || "").trim();
  if (!text) return "请求失败";
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string" && data.detail.trim()) {
      return data.detail.trim();
    }
    if (Array.isArray(data.detail)) {
      const parts = data.detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return "";
        })
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  } catch {
    /* not JSON */
  }
  return text.length > 200 ? `${text.slice(0, 200)}…` : text;
}

function isAuthFailure(status: number, detail: string): boolean {
  if (status === 401) return true;
  const d = detail.toLowerCase();
  return (
    d.includes("invalid token") ||
    d.includes("missing token") ||
    d.includes("not authenticated") ||
    d.includes("agent inactive")
  );
}

function friendlyAuthMessage(detail: string): string {
  const d = detail.toLowerCase();
  if (d.includes("invalid credentials")) return "邮箱或密码错误";
  if (d.includes("agent inactive")) return "账号已停用，请联系管理员";
  if (
    d.includes("invalid token") ||
    d.includes("missing token") ||
    d.includes("not authenticated")
  ) {
    return "登录已失效，请重新登录";
  }
  return "登录已失效，请重新登录";
}

/** Never surface raw API JSON blobs in the UI. */
export function userFacingError(err: unknown, fallback = "请求失败"): string {
  if (err instanceof ApiError) return err.detail;
  const msg = err instanceof Error ? err.message : fallback;
  const trimmed = msg.trim();
  if (trimmed.startsWith("{") && trimmed.includes('"detail"')) {
    return parseDetail(trimmed);
  }
  return msg || fallback;
}

async function handleResponse<T>(res: Response, opts?: { allowAuthRedirect?: boolean }): Promise<T> {
  if (res.ok) return res.json() as Promise<T>;

  const raw = await res.text();
  const detail = parseDetail(raw);
  const authFailed = isAuthFailure(res.status, detail);
  const allowRedirect = opts?.allowAuthRedirect !== false;

  if (authFailed && allowRedirect) {
    forceLogout(friendlyAuthMessage(detail));
  }

  const message =
    authFailed
      ? friendlyAuthMessage(detail)
      : res.status === 400 || res.status === 403 || res.status === 404 || res.status >= 500
        ? detail
        : detail;

  throw new ApiError(res.status, message, authFailed);
}

export async function login(email: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  // Login must not redirect on 401 (invalid credentials)
  return handleResponse<LoginResult>(res, { allowAuthRedirect: false });
}

export async function listConversations(token: string, queue?: string): Promise<Conversation[]> {
  const q = queue ? `?queue=${encodeURIComponent(queue)}` : "";
  const res = await fetch(`${API_BASE}/api/conversations${q}`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse<Conversation[]>(res);
}

export async function getConversation(token: string, id: string): Promise<ConversationDetail> {
  const res = await fetch(`${API_BASE}/api/conversations/${id}`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse<ConversationDetail>(res);
}

export async function sendMessage(token: string, id: string, body: string, asNote = false) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}/messages`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ body, as_note: asNote }),
  });
  return handleResponse(res);
}

export async function assignMe(token: string, id: string) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}/assign`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({}),
  });
  return handleResponse(res);
}

export async function closeConversation(token: string, id: string) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}/close`, {
    method: "POST",
    headers: authHeaders(token),
  });
  return handleResponse(res);
}

export type LangBlock = {
  id: string;
  en: string;
  zh: string;
  label: string;
};

export type FaqItem = {
  id: number | string | null;
  source?: string | null;
  sheet?: string | null;
  category: LangBlock;
  question: LangBlock;
  answer: LangBlock;
};

export type FaqListResult = {
  count: number;
  items: FaqItem[];
};

export type UnknownQuestion = {
  id?: string | null;
  date?: string | null;
  recorded_at?: string | null;
  question?: string | null;
  status?: string | null;
  external_code?: string | null;
  conversation_id?: string | null;
  reason?: string | null;
};

export type UnknownListResult = {
  count: number;
  total_matching: number;
  items: UnknownQuestion[];
};

export async function listFaq(token: string): Promise<FaqListResult> {
  const res = await fetch(`${API_BASE}/api/knowledge/faq`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse<FaqListResult>(res);
}

export async function listUnknowns(
  token: string,
  status = "open"
): Promise<UnknownListResult> {
  const q = `?status=${encodeURIComponent(status)}`;
  const res = await fetch(`${API_BASE}/api/knowledge/unknowns${q}`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse<UnknownListResult>(res);
}

export function wsUrl(token: string) {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/ws?token=${encodeURIComponent(token)}`;
}

export { API_BASE, TOKEN_KEY, AGENT_KEY };
