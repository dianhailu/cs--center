"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConsoleTopbar from "@/components/ConsoleTopbar";
import {
  AdminUser,
  CountryRow,
  ProductRow,
  createAdminCountry,
  createAdminProduct,
  createAdminUser,
  getStoredAgent,
  getStoredToken,
  listAdminCountries,
  listAdminProducts,
  listAdminUsers,
  updateAdminProduct,
  updateAdminUser,
  userFacingError,
} from "@/lib/api";

const ROLE_OPTIONS = [
  { value: "system_admin", label: "系统管理员" },
  { value: "country_admin", label: "国家管理员" },
  { value: "product_admin", label: "产品管理员" },
  { value: "agent", label: "坐席" },
];

const ROLE_HINT: Record<string, string> = {
  system_admin: "全部国家/产品；可管理目录与用户",
  country_admin: "需明确勾选国家 + 产品（不会自动拥有该国全部产品）",
  product_admin: "可编辑知识库、管理坐席；范围=产品",
  agent: "收件箱回复；知识库只读",
};

function roleLabel(role: string): string {
  return ROLE_OPTIONS.find((r) => r.value === role)?.label || role;
}

export default function AdminPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [me, setMe] = useState(getStoredAgent());
  const [tab, setTab] = useState<"users" | "products" | "countries">("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [countries, setCountries] = useState<CountryRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [userForm, setUserForm] = useState({
    email: "",
    name: "",
    password: "",
    role: "agent",
    product_codes: [] as string[],
    country_codes: [] as string[],
  });
  const [editUserId, setEditUserId] = useState<string | null>(null);

  const [productForm, setProductForm] = useState({
    code: "",
    name: "",
    customer_reply_lang: "id",
    default_country_code: "ID",
    country_codes: ["ID"] as string[],
  });
  const [editProductCode, setEditProductCode] = useState<string | null>(null);

  const [countryForm, setCountryForm] = useState({
    code: "",
    name_zh: "",
    name_en: "",
    name_local: "",
  });

  const creatableRoles = useMemo(() => {
    const role = me?.role || "agent";
    if (role === "system_admin") return ROLE_OPTIONS;
    if (role === "country_admin")
      return ROLE_OPTIONS.filter((r) =>
        ["product_admin", "agent"].includes(r.value)
      );
    if (role === "product_admin")
      return ROLE_OPTIONS.filter((r) => r.value === "agent");
    return [];
  }, [me?.role]);

  async function reload(t: string) {
    const [u, p, c] = await Promise.all([
      listAdminUsers(t),
      listAdminProducts(t),
      listAdminCountries(t),
    ]);
    setUsers(u);
    setProducts(p);
    setCountries(c);
  }

  useEffect(() => {
    const t = getStoredToken();
    const agent = getStoredAgent();
    if (!t || !agent) {
      router.replace("/login/");
      return;
    }
    if (!agent.can_manage_users && !agent.can_manage_catalog) {
      router.replace("/inbox/");
      return;
    }
    setToken(t);
    setMe(agent);
    if (!agent.can_manage_catalog) setTab("users");
    reload(t).catch((err) => setError(userFacingError(err)));
  }, [router]);

  function toggleCode(
    list: string[],
    code: string,
    on: (next: string[]) => void
  ) {
    on(list.includes(code) ? list.filter((x) => x !== code) : [...list, code]);
  }

  async function submitUser(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    setError("");
    try {
      if (editUserId) {
        await updateAdminUser(token, editUserId, {
          name: userForm.name,
          password: userForm.password || undefined,
          role: userForm.role,
          product_codes: userForm.product_codes,
          country_codes: userForm.country_codes,
        });
      } else {
        await createAdminUser(token, {
          email: userForm.email,
          name: userForm.name,
          password: userForm.password,
          role: userForm.role,
          product_codes: userForm.product_codes,
          country_codes: userForm.country_codes,
        });
      }
      setUserForm({
        email: "",
        name: "",
        password: "",
        role: creatableRoles[0]?.value || "agent",
        product_codes: me?.product_codes?.slice(0, 1) || [],
        country_codes: me?.country_codes?.slice(0, 1) || [],
      });
      setEditUserId(null);
      await reload(token);
    } catch (err) {
      setError(userFacingError(err, "保存用户失败"));
    } finally {
      setBusy(false);
    }
  }

  async function submitProduct(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    setError("");
    try {
      const payload = {
        code: productForm.code,
        name: productForm.name,
        customer_reply_lang: productForm.customer_reply_lang,
        default_country_code: productForm.default_country_code || null,
        country_codes: productForm.country_codes,
      };
      if (editProductCode) {
        await updateAdminProduct(token, editProductCode, payload);
      } else {
        await createAdminProduct(token, payload);
      }
      setProductForm({
        code: "",
        name: "",
        customer_reply_lang: "id",
        default_country_code: "ID",
        country_codes: ["ID"],
      });
      setEditProductCode(null);
      await reload(token);
    } catch (err) {
      setError(userFacingError(err, "保存产品失败"));
    } finally {
      setBusy(false);
    }
  }

  async function submitCountry(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    setError("");
    try {
      await createAdminCountry(token, countryForm);
      setCountryForm({ code: "", name_zh: "", name_en: "", name_local: "" });
      await reload(token);
    } catch (err) {
      setError(userFacingError(err, "创建国家失败"));
    } finally {
      setBusy(false);
    }
  }

  function startEditUser(u: AdminUser) {
    setEditUserId(u.id);
    setUserForm({
      email: u.email,
      name: u.name,
      password: "",
      role: u.role,
      product_codes: u.product_codes,
      country_codes: u.country_codes,
    });
    setTab("users");
  }

  function startEditProduct(p: ProductRow) {
    setEditProductCode(p.code);
    setProductForm({
      code: p.code,
      name: p.name,
      customer_reply_lang: p.customer_reply_lang,
      default_country_code: p.default_country_code || "",
      country_codes: p.country_codes,
    });
    setTab("products");
  }

  return (
    <div className="shell">
      <ConsoleTopbar />
      <main className="admin-page">
        <div className="admin-header">
          <h1>账户与权限</h1>
          <p className="muted">
            当前角色：{roleLabel(me?.role || "")}
            {me?.customer_reply_lang
              ? ` · 当前产品强制回复语：${me.customer_reply_lang}`
              : ""}
          </p>
        </div>

        <div className="admin-tabs">
          <button
            type="button"
            className={tab === "users" ? "" : "secondary"}
            onClick={() => setTab("users")}
          >
            用户
          </button>
          {me?.can_manage_catalog ? (
            <>
              <button
                type="button"
                className={tab === "products" ? "" : "secondary"}
                onClick={() => setTab("products")}
              >
                产品
              </button>
              <button
                type="button"
                className={tab === "countries" ? "" : "secondary"}
                onClick={() => setTab("countries")}
              >
                国家
              </button>
            </>
          ) : null}
        </div>

        {error ? <div className="error">{error}</div> : null}

        {tab === "users" && me?.can_manage_users ? (
          <div className="admin-grid">
            <form className="admin-card" onSubmit={submitUser}>
              <h2>{editUserId ? "编辑用户" : "创建用户"}</h2>
              <p className="muted">{ROLE_HINT[userForm.role]}</p>
              {!editUserId ? (
                <label className="field">
                  <span>Email</span>
                  <input
                    type="email"
                    required
                    value={userForm.email}
                    onChange={(e) =>
                      setUserForm((f) => ({ ...f, email: e.target.value }))
                    }
                  />
                </label>
              ) : (
                <p className="muted">{userForm.email}</p>
              )}
              <label className="field">
                <span>姓名</span>
                <input
                  required
                  value={userForm.name}
                  onChange={(e) =>
                    setUserForm((f) => ({ ...f, name: e.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>{editUserId ? "新密码（可选）" : "密码"}</span>
                <input
                  type="password"
                  required={!editUserId}
                  minLength={6}
                  value={userForm.password}
                  onChange={(e) =>
                    setUserForm((f) => ({ ...f, password: e.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>角色</span>
                <select
                  value={userForm.role}
                  onChange={(e) =>
                    setUserForm((f) => ({ ...f, role: e.target.value }))
                  }
                >
                  {creatableRoles.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </label>
              {userForm.role !== "system_admin" ? (
                <>
                  <fieldset className="admin-checkset">
                    <legend>产品（必选）</legend>
                    {products.map((p) => (
                      <label key={p.code} className="admin-check">
                        <input
                          type="checkbox"
                          checked={userForm.product_codes.includes(p.code)}
                          onChange={() =>
                            toggleCode(
                              userForm.product_codes,
                              p.code,
                              (product_codes) =>
                                setUserForm((f) => ({ ...f, product_codes }))
                            )
                          }
                        />
                        {p.name} ({p.code})
                      </label>
                    ))}
                  </fieldset>
                  {(userForm.role === "country_admin" ||
                    userForm.country_codes.length > 0 ||
                    countries.length > 0) && (
                    <fieldset className="admin-checkset">
                      <legend>
                        国家
                        {userForm.role === "country_admin" ? "（必选）" : "（可选）"}
                      </legend>
                      {countries.map((c) => (
                        <label key={c.code} className="admin-check">
                          <input
                            type="checkbox"
                            checked={userForm.country_codes.includes(c.code)}
                            onChange={() =>
                              toggleCode(
                                userForm.country_codes,
                                c.code,
                                (country_codes) =>
                                  setUserForm((f) => ({ ...f, country_codes }))
                              )
                            }
                          />
                          {c.name_zh || c.name_en} ({c.code})
                        </label>
                      ))}
                    </fieldset>
                  )}
                </>
              ) : null}
              <div className="admin-actions">
                <button type="submit" disabled={busy}>
                  {editUserId ? "保存" : "创建"}
                </button>
                {editUserId ? (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setEditUserId(null);
                      setUserForm({
                        email: "",
                        name: "",
                        password: "",
                        role: "agent",
                        product_codes: [],
                        country_codes: [],
                      });
                    }}
                  >
                    取消
                  </button>
                ) : null}
              </div>
            </form>

            <div className="admin-card">
              <h2>用户列表</h2>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>邮箱</th>
                    <th>角色</th>
                    <th>产品</th>
                    <th>国家</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td>
                        <div>{u.name}</div>
                        <div className="muted">{u.email}</div>
                      </td>
                      <td>{roleLabel(u.role)}</td>
                      <td>{u.product_codes.join(", ") || "—"}</td>
                      <td>{u.country_codes.join(", ") || "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => startEditUser(u)}
                        >
                          编辑
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {tab === "products" && me?.can_manage_catalog ? (
          <div className="admin-grid">
            <form className="admin-card" onSubmit={submitProduct}>
              <h2>{editProductCode ? "编辑产品" : "创建产品"}</h2>
              <label className="field">
                <span>Code</span>
                <input
                  required
                  disabled={Boolean(editProductCode)}
                  value={productForm.code}
                  onChange={(e) =>
                    setProductForm((f) => ({
                      ...f,
                      code: e.target.value.toLowerCase(),
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>名称</span>
                <input
                  required
                  value={productForm.name}
                  onChange={(e) =>
                    setProductForm((f) => ({ ...f, name: e.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>客户回复强制语言</span>
                <select
                  value={productForm.customer_reply_lang}
                  onChange={(e) =>
                    setProductForm((f) => ({
                      ...f,
                      customer_reply_lang: e.target.value,
                    }))
                  }
                >
                  <option value="id">id · 印尼语</option>
                  <option value="zh">zh · 中文</option>
                  <option value="en">en · English</option>
                </select>
              </label>
              <label className="field">
                <span>默认国家</span>
                <select
                  value={productForm.default_country_code}
                  onChange={(e) =>
                    setProductForm((f) => ({
                      ...f,
                      default_country_code: e.target.value,
                    }))
                  }
                >
                  <option value="">—</option>
                  {countries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name_zh} ({c.code})
                    </option>
                  ))}
                </select>
              </label>
              <fieldset className="admin-checkset">
                <legend>关联国家</legend>
                {countries.map((c) => (
                  <label key={c.code} className="admin-check">
                    <input
                      type="checkbox"
                      checked={productForm.country_codes.includes(c.code)}
                      onChange={() =>
                        toggleCode(
                          productForm.country_codes,
                          c.code,
                          (country_codes) =>
                            setProductForm((f) => ({ ...f, country_codes }))
                        )
                      }
                    />
                    {c.name_zh} ({c.code})
                  </label>
                ))}
              </fieldset>
              <div className="admin-actions">
                <button type="submit" disabled={busy}>
                  {editProductCode ? "保存" : "创建"}
                </button>
                {editProductCode ? (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setEditProductCode(null);
                      setProductForm({
                        code: "",
                        name: "",
                        customer_reply_lang: "id",
                        default_country_code: "ID",
                        country_codes: ["ID"],
                      });
                    }}
                  >
                    取消
                  </button>
                ) : null}
              </div>
            </form>
            <div className="admin-card">
              <h2>产品列表</h2>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>产品</th>
                    <th>回复语言</th>
                    <th>国家</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {products.map((p) => (
                    <tr key={p.code}>
                      <td>
                        {p.name} <span className="muted">({p.code})</span>
                      </td>
                      <td>{p.customer_reply_lang}</td>
                      <td>{p.country_codes.join(", ")}</td>
                      <td>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => startEditProduct(p)}
                        >
                          编辑
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {tab === "countries" && me?.can_manage_catalog ? (
          <div className="admin-grid">
            <form className="admin-card" onSubmit={submitCountry}>
              <h2>创建国家</h2>
              <label className="field">
                <span>Code（如 ID）</span>
                <input
                  required
                  value={countryForm.code}
                  onChange={(e) =>
                    setCountryForm((f) => ({
                      ...f,
                      code: e.target.value.toUpperCase(),
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>中文名</span>
                <input
                  value={countryForm.name_zh}
                  onChange={(e) =>
                    setCountryForm((f) => ({ ...f, name_zh: e.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>English</span>
                <input
                  value={countryForm.name_en}
                  onChange={(e) =>
                    setCountryForm((f) => ({ ...f, name_en: e.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>本地名</span>
                <input
                  value={countryForm.name_local}
                  onChange={(e) =>
                    setCountryForm((f) => ({
                      ...f,
                      name_local: e.target.value,
                    }))
                  }
                />
              </label>
              <button type="submit" disabled={busy}>
                创建
              </button>
            </form>
            <div className="admin-card">
              <h2>国家列表</h2>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>中文</th>
                    <th>EN</th>
                    <th>本地</th>
                  </tr>
                </thead>
                <tbody>
                  {countries.map((c) => (
                    <tr key={c.code}>
                      <td>{c.code}</td>
                      <td>{c.name_zh}</td>
                      <td>{c.name_en}</td>
                      <td>{c.name_local}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
