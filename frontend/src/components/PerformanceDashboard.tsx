"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type Totals = {
  bugs_found: number;
  fixes_suggested: number;
  fixes_verified: number;
  fixes_approved: number;
  prs_opened: number;
  failed_fix_attempts: number;
  avg_run_seconds: number | null;
  avg_time_to_fix_seconds: number | null;
  tokens_per_run: number | null;
  cost_per_run: number | null;
  total_tokens: number;
  total_cost_usd: number;
};

type Perf = {
  range: string;
  totals: Totals;
  severity_by_week: {
    label: string;
    critical: number;
    high: number;
    medium: number;
    low: number;
  }[];
  success_by_week: {
    label: string;
    suggested: number;
    approved: number;
    rate: number;
  }[];
  recent_runs: {
    id: string;
    repository_full_name: string | null;
    branch: string;
    test_env: string | null;
    bugs_found: number;
    fixes_verified: number;
    status: string;
    duration_seconds: number | null;
    tokens: number;
    cost_usd: number;
    created_at: string;
  }[];
};

type RangeKey = "7d" | "30d" | "all";

function apiBase() {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
    /\/$/,
    ""
  );
}

async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

function fmtDuration(sec: number | null) {
  if (sec == null) return "—";
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

function fmtTokens(n: number | null) {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(Math.round(n));
}

function fmtCost(n: number | null) {
  if (n == null) return "—";
  return `$${n.toFixed(n < 0.01 ? 4 : 2)}`;
}

function exportCsv(data: Perf) {
  const lines = [
    "run_id,repo,branch,test_env,bugs,fixes_verified,status,duration_s,tokens,cost_usd",
    ...data.recent_runs.map((r) =>
      [
        r.id,
        r.repository_full_name || "",
        r.branch,
        r.test_env || "",
        r.bugs_found,
        r.fixes_verified,
        r.status,
        r.duration_seconds ?? "",
        r.tokens,
        r.cost_usd,
      ].join(",")
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `rino-performance-${data.range}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Stacked severity bars (wireframe-faithful; no chart lib required). */
function SeverityBars({
  rows,
}: {
  rows: Perf["severity_by_week"];
}) {
  const max = Math.max(
    1,
    ...rows.map((r) => r.critical + r.high + r.medium + r.low)
  );
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-end gap-5 h-[170px] border-b border-rino-border px-2">
        {rows.map((r) => {
          const total = r.critical + r.high + r.medium + r.low;
          const h = (n: number) => `${Math.max(2, (n / max) * 150)}px`;
          return (
            <div
              key={r.label}
              className="flex-1 flex flex-col justify-end gap-0.5"
              title={`${r.label}: ${total}`}
            >
              {r.low > 0 ? (
                <i className="block rounded-sm bg-[#CBD5E1]" style={{ height: h(r.low) }} />
              ) : null}
              {r.medium > 0 ? (
                <i className="block rounded-sm bg-[#FACC15]" style={{ height: h(r.medium) }} />
              ) : null}
              {r.high > 0 ? (
                <i className="block rounded-sm bg-[#F97316]" style={{ height: h(r.high) }} />
              ) : null}
              {r.critical > 0 ? (
                <i
                  className="block rounded-sm bg-[#DC2626]"
                  style={{ height: h(r.critical) }}
                />
              ) : null}
              {total === 0 ? (
                <i className="block rounded-sm bg-[#F5F5F4]" style={{ height: 8 }} />
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="flex gap-5 px-2 text-[11px] text-rino-muted">
        {rows.map((r) => (
          <span key={r.label} className="flex-1 text-center">
            {r.label}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-[#44403C]">
        <span>
          <i className="inline-block w-2.5 h-2.5 rounded-sm bg-[#DC2626] mr-1.5 align-middle" />
          Critical
        </span>
        <span>
          <i className="inline-block w-2.5 h-2.5 rounded-sm bg-[#F97316] mr-1.5 align-middle" />
          High
        </span>
        <span>
          <i className="inline-block w-2.5 h-2.5 rounded-sm bg-[#FACC15] mr-1.5 align-middle" />
          Medium
        </span>
        <span>
          <i className="inline-block w-2.5 h-2.5 rounded-sm bg-[#CBD5E1] mr-1.5 align-middle" />
          Low
        </span>
      </div>
    </div>
  );
}

function SuccessLine({ rows }: { rows: Perf["success_by_week"] }) {
  const points = useMemo(() => {
    const w = 360;
    const h = 160;
    const pad = 20;
    if (rows.length === 0) return "";
    return rows
      .map((r, i) => {
        const x =
          pad + (i * (w - pad * 2)) / Math.max(rows.length - 1, 1);
        const y = pad + ((100 - r.rate) / 100) * (h - pad * 2);
        return `${x},${y}`;
      })
      .join(" ");
  }, [rows]);

  return (
    <div className="flex flex-col gap-2">
      <svg viewBox="0 0 360 160" className="w-full h-[170px]">
        <line x1="20" y1="140" x2="340" y2="140" stroke="#E7E5E4" />
        <polyline
          fill="none"
          stroke="#4338CA"
          strokeWidth="2.5"
          points={points}
        />
        {rows.map((r, i) => {
          const x =
            20 + (i * 320) / Math.max(rows.length - 1, 1);
          const y = 20 + ((100 - r.rate) / 100) * 120;
          return (
            <g key={r.label}>
              <circle cx={x} cy={y} r="4" fill="#4338CA" />
              <text
                x={x}
                y="155"
                textAnchor="middle"
                fontSize="11"
                fill="#78716C"
              >
                {r.label}
              </text>
              <text
                x={x}
                y={y - 10}
                textAnchor="middle"
                fontSize="10"
                fill="#44403C"
              >
                {r.rate}%
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function PerformanceDashboard() {
  const [range, setRange] = useState<RangeKey>("30d");
  const [data, setData] = useState<Perf | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (r: RangeKey) => {
    const dash = await api<Perf>(`/api/developer/performance?range=${r}`);
    setData(dash);
  }, []);

  useEffect(() => {
    load(range).catch((e: Error) => setError(e.message));
  }, [range, load]);

  const t = data?.totals;

  return (
    <div className="flex flex-col gap-5">
      {error ? (
        <p className="m-0 text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2 items-center justify-between">
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["30d", "Last 30 days"],
              ["7d", "Last 7 days"],
              ["all", "All time"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setRange(k)}
              className={`min-h-9 px-3.5 rounded-full text-sm font-medium border ${
                range === k
                  ? "bg-rino-indigoSoft text-rino-indigo border-transparent"
                  : "bg-white text-rino-muted border-[#D6D3D1] hover:bg-[#F5F5F4]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled={!data}
          onClick={() => data && exportCsv(data)}
          className="min-h-9 px-3.5 rounded-[10px] border border-[#D6D3D1] bg-white text-sm font-semibold hover:bg-[#F5F5F4] disabled:opacity-50"
        >
          Export CSV
        </button>
      </div>

      <div className="grid gap-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 bg-white border border-rino-border rounded-2xl shadow-card overflow-hidden">
        {(
          [
            ["Bugs found", t?.bugs_found],
            ["Fixes suggested", t?.fixes_suggested],
            ["Fixes verified", t?.fixes_verified],
            ["Fixes approved", t?.fixes_approved],
            ["PRs opened", t?.prs_opened],
            ["Failed fix attempts", t?.failed_fix_attempts],
          ] as const
        ).map(([label, val], i, arr) => (
          <div
            key={label}
            className={`px-4 py-3.5 flex flex-col gap-1 ${
              i < arr.length - 1 ? "xl:border-r border-[#F0EFED]" : ""
            }`}
          >
            <span className="text-xs text-rino-muted font-medium">{label}</span>
            <span className="text-[22px] font-bold tracking-tight">
              {val ?? "—"}
            </span>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Avg run time", fmtDuration(t?.avg_run_seconds ?? null)],
            ["Avg time to fix", fmtDuration(t?.avg_time_to_fix_seconds ?? null)],
            ["Tokens per run", fmtTokens(t?.tokens_per_run ?? null)],
            ["Cost per run", fmtCost(t?.cost_per_run ?? null)],
          ] as const
        ).map(([label, val]) => (
          <div
            key={label}
            className="bg-white border border-rino-border rounded-2xl px-4 py-3.5 shadow-card flex flex-col gap-1"
          >
            <span className="text-xs text-rino-muted font-medium">{label}</span>
            <span className="text-lg font-semibold tracking-tight">{val}</span>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="bg-white border border-rino-border rounded-2xl p-5 shadow-card flex flex-col gap-3">
          <h2 className="m-0 text-[15px] font-semibold">
            Findings by severity
          </h2>
          <SeverityBars rows={data?.severity_by_week || []} />
        </section>

        <section className="bg-white border border-rino-border rounded-2xl p-5 shadow-card flex flex-col gap-3">
          <h2 className="m-0 text-[15px] font-semibold">Fix success rate</h2>
          <p className="m-0 text-xs text-rino-muted">approved ÷ suggested</p>
          <SuccessLine rows={data?.success_by_week || []} />
        </section>
      </div>

      <section className="bg-white border border-rino-border rounded-2xl shadow-card overflow-hidden">
        <div className="px-5 py-4 border-b border-rino-border">
          <h2 className="m-0 text-[15px] font-semibold">Recent runs</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse min-w-[900px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-rino-muted bg-[#FAFAF9]">
                {(
                  [
                    "Run ID",
                    "Repo",
                    "Branch",
                    "Test env",
                    "Bugs",
                    "Fixes verified",
                    "Status",
                    "Duration",
                    "Tokens",
                    "Cost",
                  ] as const
                ).map((h) => (
                  <th key={h} className="px-4 py-3 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data?.recent_runs || []).length === 0 ? (
                <tr>
                  <td
                    colSpan={10}
                    className="px-4 py-8 text-center text-rino-muted"
                  >
                    No runs in this range yet.
                  </td>
                </tr>
              ) : (
                data!.recent_runs.map((r) => (
                  <tr
                    key={r.id}
                    className="border-t border-[#F0EFED] hover:bg-[#FAFAF9]"
                  >
                    <td className="px-4 py-3 font-mono text-xs">
                      {r.id.slice(0, 8)}
                    </td>
                    <td className="px-4 py-3">
                      {r.repository_full_name || "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{r.branch}</td>
                    <td className="px-4 py-3 text-xs">{r.test_env || "—"}</td>
                    <td className="px-4 py-3">{r.bugs_found}</td>
                    <td className="px-4 py-3">{r.fixes_verified}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${
                          r.status === "succeeded"
                            ? "bg-[#F0FDF4] text-[#15803D]"
                            : r.status === "failed" || r.status === "timed_out"
                              ? "bg-[#FEF2F2] text-[#B91C1C]"
                              : "bg-[#F5F5F4] text-rino-muted"
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {fmtDuration(r.duration_seconds)}
                    </td>
                    <td className="px-4 py-3">{fmtTokens(r.tokens)}</td>
                    <td className="px-4 py-3">{fmtCost(r.cost_usd)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
