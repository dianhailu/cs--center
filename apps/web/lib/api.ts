const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8080";

const TOKEN_KEY = "cs_token";
const AGENT_KEY = "cs_agent";

export type Scope = {
  workspace_id: string;
  workspace_name: string;
  product_code: string;
  product_name: string;
  country_code: string;
  country_name: string;
  customer_reply_lang: string;
};

export type LoginResult = {
  access_token: string;
  agent_id: string;
  email: string;
  name: string;
  role: string;
  workspace_id: string;
  workspace_name: string;
  product_code: string;
  country_code: string;
  customer_reply_lang: string;
  product_codes: string[];
  country_codes: string[];
  scopes: Scope[];
  can_edit_knowledge: boolean;
  can_manage_users: boolean;
  can_manage_catalog: boolean;
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

export function getStoredAgent(): LoginResult | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(AGENT_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as LoginResult;
  } catch {
    return null;
  }
}

export function saveSession(result: LoginResult) {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, result.access_token);
  localStorage.setItem(AGENT_KEY, JSON.stringify(result));
}

export function contextLabel(agent?: LoginResult | null): string {
  if (!agent) return "客服台";
  const scope = (agent.scopes || []).find((s) => s.workspace_id === agent.workspace_id);
  const product = scope?.product_name || agent.product_code || "";
  const country = scope?.country_name || agent.country_code || "";
  if (product && country) return `${product} · ${country}`;
  return agent.workspace_name || product || "客服台";
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

export async function switchContext(
  token: string,
  body: { workspace_id?: string; product_code?: string; country_code?: string }
): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/api/auth/switch`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse<LoginResult>(res);
}

export async function fetchMe(token: string): Promise<LoginResult & { agent_id: string }> {
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse(res);
}

export type CountryRow = {
  code: string;
  name_zh: string;
  name_en: string;
  name_local: string;
};

export type ProductRow = {
  code: string;
  name: string;
  customer_reply_lang: string;
  default_country_code: string | null;
  country_codes: string[];
};

export type AdminUser = {
  id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  product_codes: string[];
  country_codes: string[];
};

export async function listAdminCountries(token: string): Promise<CountryRow[]> {
  const res = await fetch(`${API_BASE}/api/admin/countries`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse(res);
}

export async function createAdminCountry(
  token: string,
  body: Partial<CountryRow> & { code: string }
): Promise<CountryRow> {
  const res = await fetch(`${API_BASE}/api/admin/countries`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function updateAdminCountry(
  token: string,
  code: string,
  body: Partial<CountryRow>
): Promise<CountryRow> {
  const res = await fetch(`${API_BASE}/api/admin/countries/${encodeURIComponent(code)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function listAdminProducts(token: string): Promise<ProductRow[]> {
  const res = await fetch(`${API_BASE}/api/admin/products`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse(res);
}

export async function createAdminProduct(
  token: string,
  body: {
    code: string;
    name: string;
    customer_reply_lang: string;
    default_country_code?: string | null;
    country_codes?: string[];
  }
): Promise<ProductRow> {
  const res = await fetch(`${API_BASE}/api/admin/products`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function updateAdminProduct(
  token: string,
  code: string,
  body: {
    code?: string;
    name: string;
    customer_reply_lang: string;
    default_country_code?: string | null;
    country_codes?: string[];
  }
): Promise<ProductRow> {
  const res = await fetch(`${API_BASE}/api/admin/products/${encodeURIComponent(code)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function listAdminUsers(token: string): Promise<AdminUser[]> {
  const res = await fetch(`${API_BASE}/api/admin/users`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse(res);
}

export async function createAdminUser(
  token: string,
  body: {
    email: string;
    name: string;
    password: string;
    role: string;
    product_codes: string[];
    country_codes: string[];
    is_active?: boolean;
  }
): Promise<AdminUser> {
  const res = await fetch(`${API_BASE}/api/admin/users`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function updateAdminUser(
  token: string,
  id: string,
  body: {
    name?: string;
    password?: string;
    role?: string;
    product_codes?: string[];
    country_codes?: string[];
    is_active?: boolean;
  }
): Promise<AdminUser> {
  const res = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function listConversations(
  token: string,
  queue?: string,
  search?: string
): Promise<Conversation[]> {
  const params = new URLSearchParams();
  if (queue) params.set("queue", queue);
  const trimmed = (search || "").trim();
  if (trimmed) params.set("q", trimmed);
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/conversations${qs ? `?${qs}` : ""}`, {
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
  code?: string | null;
  category_slug?: string | null;
  product_code?: string | null;
  source?: string | null;
  updated_by?: string | null;
  updated_at?: string | null;
  source_detail?: string | null;
  sheet?: string | null;
  category: LangBlock;
  question: LangBlock;
  answer: LangBlock;
};

export type FaqListResult = {
  count: number;
  items: FaqItem[];
};

export type LangTriple = {
  zh: string;
  id: string;
  en: string;
};

export type KnowledgeCategory = {
  slug: string;
  count: number;
  label: LangBlock;
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
  suggested_draft?: string | null;
  draft_answer?: LangTriple | null;
  answer?: LangTriple | string | null;
  faq_id?: number | null;
  answered_at?: string | null;
  updated_at?: string | null;
};

export type UnknownListResult = {
  count: number;
  total_matching: number;
  items: UnknownQuestion[];
};

export type FaqWritePayload = {
  question: LangTriple;
  answer: LangTriple;
  category?: LangTriple;
  category_slug?: string;
  code?: string;
  auto_translate?: boolean;
  source_lang?: "zh" | "id" | "en";
};

export async function listFaq(token: string): Promise<FaqListResult> {
  const res = await fetch(`${API_BASE}/api/knowledge/faq`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse<FaqListResult>(res);
}

export async function listKnowledgeCategories(
  token: string
): Promise<{ count: number; items: KnowledgeCategory[] }> {
  const res = await fetch(`${API_BASE}/api/knowledge/categories`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse(res);
}

export async function createKnowledgeCategory(
  token: string,
  body: { slug: string; label?: LangTriple }
): Promise<{ item: KnowledgeCategory }> {
  const res = await fetch(`${API_BASE}/api/knowledge/categories`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function createFaq(
  token: string,
  body: FaqWritePayload
): Promise<{ item: FaqItem; warnings?: string[] }> {
  const res = await fetch(`${API_BASE}/api/knowledge/faq`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function updateFaq(
  token: string,
  id: number | string,
  body: Partial<FaqWritePayload>
): Promise<{ item: FaqItem; warnings?: string[] }> {
  const res = await fetch(`${API_BASE}/api/knowledge/faq/${id}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
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

export async function updateUnknown(
  token: string,
  id: string,
  body: {
    question?: string;
    draft_answer?: LangTriple;
    suggested_draft?: string;
  }
): Promise<{ item: UnknownQuestion }> {
  const res = await fetch(`${API_BASE}/api/knowledge/unknowns/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

export async function resolveUnknown(
  token: string,
  id: string,
  body: FaqWritePayload
): Promise<{ faq: FaqItem; unknown: UnknownQuestion; warnings?: string[] }> {
  const res = await fetch(
    `${API_BASE}/api/knowledge/unknowns/${encodeURIComponent(id)}/resolve`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
    }
  );
  return handleResponse(res);
}

export type DailyStatDay = {
  date: string;
  unique_people: number;
  consultations_count: number;
};

export type DailyStatsResult = {
  timezone: string;
  from: string;
  to: string;
  days: DailyStatDay[];
};

export type CategoryStat = {
  key: string;
  label: string;
  count: number;
};

export type DailyCategoriesResult = {
  date: string;
  timezone: string;
  total_questions: number;
  categories: CategoryStat[];
};

export async function getDailyStats(
  token: string,
  from: string,
  to: string
): Promise<DailyStatsResult> {
  const q = `?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
  const res = await fetch(`${API_BASE}/api/stats/daily${q}`, {
    headers: authHeaders(token),
    cache: "no-store",
  });
  return handleResponse(res);
}

export async function getDailyCategories(
  token: string,
  date: string
): Promise<DailyCategoriesResult> {
  const res = await fetch(
    `${API_BASE}/api/stats/daily/${encodeURIComponent(date)}/categories`,
    {
      headers: authHeaders(token),
      cache: "no-store",
    }
  );
  return handleResponse(res);
}

export function wsUrl(token: string) {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/ws?token=${encodeURIComponent(token)}`;
}

export { API_BASE, TOKEN_KEY, AGENT_KEY };
