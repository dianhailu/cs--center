"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConsoleTopbar from "@/components/ConsoleTopbar";
import {
  ApiError,
  CategoryStat,
  DailyStatDay,
  getDailyCategories,
  getDailyStats,
  getStoredToken,
  userFacingError,
  AGENT_KEY,
} from "@/lib/api";

/** Format YYYY-MM-DD in Asia/Jakarta (approx via Intl). */
function jakartaYmd(d: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function addDaysYmd(ymd: string, delta: number): string {
  const [y, m, d] = ymd.split("-").map(Number);
  // Noon UTC avoids DST / timezone day-boundary skew when formatting as Jakarta.
  const dt = new Date(Date.UTC(y, m - 1, d + delta, 12, 0, 0));
  return jakartaYmd(dt);
}

function defaultRange(days = 14): { from: string; to: string } {
  const to = jakartaYmd(new Date());
  const from = addDaysYmd(to, -(days - 1));
  return { from, to };
}

function shortLabel(ymd: string): string {
  const parts = ymd.split("-");
  return `${parts[1]}/${parts[2]}`;
}

function BarChart({
  days,
  valueKey,
  color,
  selected,
  onSelect,
}: {
  days: DailyStatDay[];
  valueKey: "unique_people" | "consultations_count";
  color: string;
  selected: string | null;
  onSelect: (date: string) => void;
}) {
  const max = Math.max(1, ...days.map((d) => d[valueKey]));
  return (
    <div className="stats-bars" role="img" aria-label="柱状图">
      {days.map((d) => {
        const v = d[valueKey];
        const h = Math.max(v > 0 ? 8 : 2, Math.round((v / max) * 140));
        const active = selected === d.date;
        return (
          <button
            key={d.date}
            type="button"
            className={`stats-bar-col${active ? " active" : ""}`}
            onClick={() => onSelect(d.date)}
            title={`${d.date}: ${v}`}
          >
            <span className="stats-bar-val">{v}</span>
            <span
              className="stats-bar"
              style={{ height: h, background: color }}
            />
            <span className="stats-bar-label">{shortLabel(d.date)}</span>
          </button>
        );
      })}
    </div>
  );
}

function CategoryBars({ items }: { items: CategoryStat[] }) {
  const max = Math.max(1, ...items.map((c) => c.count));
  if (!items.length) {
    return <p className="muted">当日暂无客户进线问题</p>;
  }
  return (
    <ul className="stats-cat-list">
      {items.map((c) => (
        <li key={c.key}>
          <div className="stats-cat-row">
            <span className="stats-cat-label">{c.label}</span>
            <span className="stats-cat-count">{c.count}</span>
          </div>
          <div className="stats-cat-track">
            <div
              className="stats-cat-fill"
              style={{ width: `${Math.round((c.count / max) * 100)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function StatsPage() {
  const router = useRouter();
  const initial = useMemo(() => defaultRange(14), []);
  const [token, setToken] = useState("");
  const [agentName, setAgentName] = useState("");
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [days, setDays] = useState<DailyStatDay[]>([]);
  const [timezone, setTimezone] = useState("Asia/Jakarta");
  const [selected, setSelected] = useState<string | null>(null);
  const [categories, setCategories] = useState<CategoryStat[]>([]);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const totals = useMemo(() => {
    return days.reduce(
      (acc, d) => {
        acc.people += d.unique_people;
        acc.consults += d.consultations_count;
        return acc;
      },
      { people: 0, consults: 0 }
    );
  }, [days]);

  async function loadRange(t: string, f: string, tEnd: string) {
    setLoading(true);
    setError("");
    try {
      const res = await getDailyStats(t, f, tEnd);
      setDays(res.days || []);
      setTimezone(res.timezone || "Asia/Jakarta");
      const withData = [...(res.days || [])]
        .reverse()
        .find((d) => d.consultations_count > 0);
      const pick = withData?.date || res.days?.[res.days.length - 1]?.date || null;
      setSelected(pick);
      if (pick) {
        await loadDetail(t, pick);
      } else {
        setCategories([]);
        setTotalQuestions(0);
      }
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setError(userFacingError(err, "加载统计失败"));
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(t: string, date: string) {
    setDetailLoading(true);
    try {
      const res = await getDailyCategories(t, date);
      setCategories(res.categories || []);
      setTotalQuestions(res.total_questions || 0);
    } catch (err) {
      if (err instanceof ApiError && err.authFailed) return;
      setError(userFacingError(err, "加载分类明细失败"));
    } finally {
      setDetailLoading(false);
    }
  }

  useEffect(() => {
    const t = getStoredToken();
    const agent = localStorage.getItem(AGENT_KEY);
    if (!t) {
      router.replace("/login/");
      return;
    }
    setToken(t);
    if (agent) {
      try {
        setAgentName(JSON.parse(agent).name || "");
      } catch {
        /* ignore */
      }
    }
    void loadRange(t, from, to);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  function applyPreset(n: number) {
    const range = defaultRange(n);
    setFrom(range.from);
    setTo(range.to);
    if (token) void loadRange(token, range.from, range.to);
  }

  function onSelectDay(date: string) {
    setSelected(date);
    if (token) void loadDetail(token, date);
  }

  return (
    <div className="shell">
      <ConsoleTopbar
        subtitle={
          <>
            数据统计
            {agentName ? <span className="muted"> · {agentName}</span> : null}
          </>
        }
      />
      <main className="stats-page">
        <div className="stats-head">
          <div>
            <h1>数据统计</h1>
            <p className="muted">
              按日统计咨询人数与咨询次数（时区 {timezone}）。点击某一天查看问题分类明细。
            </p>
          </div>
          <div className="stats-filters">
            <label>
              从
              <input
                type="date"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label>
              至
              <input
                type="date"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
            <button
              type="button"
              onClick={() => token && loadRange(token, from, to)}
              disabled={loading || !token}
            >
              查询
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => applyPreset(7)}
              disabled={loading || !token}
            >
              近 7 天
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => applyPreset(14)}
              disabled={loading || !token}
            >
              近 14 天
            </button>
          </div>
        </div>

        {error ? <div className="stats-error">{error}</div> : null}

        <div className="stats-summary">
          <div className="stats-metric">
            <div className="stats-metric-label">区间咨询人次合计</div>
            <div className="stats-metric-val">{totals.people}</div>
            <div className="muted stats-metric-hint">
              各日「咨询人数」相加（同人多日会重复计入）
            </div>
          </div>
          <div className="stats-metric">
            <div className="stats-metric-label">区间咨询次数合计</div>
            <div className="stats-metric-val">{totals.consults}</div>
            <div className="muted stats-metric-hint">
              有客户进线的会话数（按日去重后相加）
            </div>
          </div>
        </div>

        {loading ? (
          <p className="muted">加载中…</p>
        ) : (
          <div className="stats-charts">
            <section className="stats-panel">
              <h2>咨询人数（去重）</h2>
              <p className="muted stats-def">
                当日有客户进线的会话中，按手机号 → 邮箱 → 联系人/访客 ID 去重后的人数；无身份信息不计入。
              </p>
              <BarChart
                days={days}
                valueKey="unique_people"
                color="var(--accent)"
                selected={selected}
                onSelect={onSelectDay}
              />
            </section>
            <section className="stats-panel">
              <h2>咨询次数</h2>
              <p className="muted stats-def">
                当日至少有一条客户进线消息的会话数（按会话计，非消息条数）。
              </p>
              <BarChart
                days={days}
                valueKey="consultations_count"
                color="var(--accent-deep)"
                selected={selected}
                onSelect={onSelectDay}
              />
            </section>
          </div>
        )}

        <section className="stats-panel stats-detail">
          <div className="stats-detail-head">
            <h2>
              分类明细
              {selected ? <span className="stats-detail-date"> · {selected}</span> : null}
            </h2>
            <p className="muted">
              按当日每条客户进线消息归类（FAQ 分类 / 接待 / 未知 / 其他）。共{" "}
              {totalQuestions} 条。
            </p>
          </div>
          {detailLoading ? (
            <p className="muted">加载明细…</p>
          ) : (
            <CategoryBars items={categories} />
          )}
        </section>
      </main>
    </div>
  );
}
