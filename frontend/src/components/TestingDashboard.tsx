"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

type Counts = {
  total: number;
  passed: number;
  failed: number;
  error: number;
  skipped: number;
  flaky: number;
  pylint: number;
  bandit: number;
};

type Row = {
  key: string;
  case_name: string | null;
  classname: string | null;
  before_status: string | null;
  after_status: string | null;
  before_message: string | null;
  after_message: string | null;
  duration_seconds: number | null;
  tag: string;
};

type Dashboard = {
  run_id: string;
  repository_full_name: string | null;
  branch: string | null;
  finding_id: string | null;
  fix_status: string | null;
  fix_branch: string | null;
  attempt_number: number | null;
  before: Counts;
  after: Counts;
  fixed_count: number;
  regression_count: number;
  note: string | null;
  rows: Row[];
  test_env: string | null;
  workflow_file: string | null;
  python_version: string | null;
};

type AnalysisRun = {
  id: string;
  repository_full_name: string | null;
  status: string;
  findings: { id: string; severity: string; fix_status: string }[];
};

type Filter = "changed" | "all" | "failed" | "flaky";

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
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function statusPill(status: string | null) {
  const s = status || "—";
  const cls =
    s === "passed"
      ? "bg-[#F0FDF4] text-[#15803D]"
      : s === "failed" || s === "error"
        ? "bg-[#FEF2F2] text-[#B91C1C]"
        : s === "skipped"
          ? "bg-[#F5F5F4] text-[#57534E]"
          : s === "flaky"
            ? "bg-[#FFF7ED] text-[#C2410C]"
            : "bg-[#F5F5F4] text-rino-muted";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${cls}`}
    >
      {s}
    </span>
  );
}

function arrow(before: number, after: number) {
  return `${before} → ${after}`;
}

export function TestingDashboard() {
  const params = useSearchParams();
  const initialRun = params.get("run") || "";
  const initialFinding = params.get("finding") || "";

  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [runId, setRunId] = useState(initialRun);
  const [findingId, setFindingId] = useState(initialFinding);
  const [data, setData] = useState<Dashboard | null>(null);
  const [filter, setFilter] = useState<Filter>("changed");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    const list = await api<AnalysisRun[]>("/api/developer/runs");
    setRuns(list);
    if (!runId && list[0]) setRunId(list[0].id);
  }, [runId]);

  const loadDashboard = useCallback(async (rid: string, fid: string) => {
    if (!rid) {
      setData(null);
      return;
    }
    const q = new URLSearchParams({ run_id: rid });
    if (fid) q.set("finding_id", fid);
    const dash = await api<Dashboard>(`/api/developer/testing?${q}`);
    setData(dash);
    if (dash.finding_id && !fid) setFindingId(dash.finding_id);
  }, []);

  useEffect(() => {
    loadRuns().catch((e: Error) => setError(e.message));
  }, [loadRuns]);

  useEffect(() => {
    if (runId) {
      loadDashboard(runId, findingId).catch((e: Error) => setError(e.message));
    }
  }, [runId, findingId, loadDashboard]);

  const findingsForRun = useMemo(() => {
    const run = runs.find((r) => r.id === runId);
    return (run?.findings || []).filter((f) =>
      ["verified", "pr_opened", "failed", "generating", "queued"].includes(
        f.fix_status
      )
    );
  }, [runs, runId]);

  const visibleRows = useMemo(() => {
    if (!data) return [];
    return data.rows.filter((r) => {
      if (filter === "all") return true;
      if (filter === "changed") return r.tag !== "unchanged";
      if (filter === "failed")
        return (
          r.after_status === "failed" ||
          r.after_status === "error" ||
          r.before_status === "failed" ||
          r.before_status === "error"
        );
      if (filter === "flaky")
        return r.before_status === "flaky" || r.after_status === "flaky";
      return true;
    });
  }, [data, filter]);

  const envLine = [
    data?.test_env === "rino_sandbox"
      ? "Rino sandbox"
      : data?.test_env === "github_actions"
        ? "GitHub Actions"
        : data?.test_env || "Sandbox",
    data?.workflow_file,
    data?.python_version ? `Python ${data.python_version}` : null,
    "both runs on the same env",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="flex flex-col gap-5">
      {error ? (
        <p className="m-0 text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3 items-end justify-between">
        <div className="flex flex-wrap gap-3 items-end">
          <label className="flex flex-col gap-1.5 min-w-[220px]">
            <span className="text-xs font-medium text-rino-muted">Run</span>
            <select
              className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 text-sm bg-white"
              value={runId}
              onChange={(e) => {
                setRunId(e.target.value);
                setFindingId("");
              }}
            >
              {runs.length === 0 ? (
                <option value="">No runs yet</option>
              ) : (
                runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.id.slice(0, 8)} · {r.repository_full_name || "repo"} ·{" "}
                    {r.status}
                  </option>
                ))
              )}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 min-w-[220px]">
            <span className="text-xs font-medium text-rino-muted">
              Fix finding
            </span>
            <select
              className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 text-sm bg-white"
              value={findingId}
              onChange={(e) => setFindingId(e.target.value)}
            >
              <option value="">Auto / baseline</option>
              {findingsForRun.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.severity} · {f.fix_status} · {f.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <Link href="/app" className="text-sm text-rino-indigo">
          ‹ Back to findings
        </Link>
      </div>

      {!data ? (
        <section className="bg-white border border-rino-border rounded-2xl p-6 text-sm text-rino-muted">
          Run an analysis (and optionally verify a fix) to compare before/after
          tests.
        </section>
      ) : (
        <>
          <div className="flex flex-wrap gap-2 items-center">
            {(["changed", "all", "failed", "flaky"] as Filter[]).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`min-h-9 px-3.5 rounded-full text-sm font-medium border ${
                  filter === f
                    ? "bg-rino-indigoSoft text-rino-indigo border-transparent"
                    : "bg-white text-rino-muted border-[#D6D3D1] hover:bg-[#F5F5F4]"
                }`}
              >
                {f === "changed"
                  ? "Changed only"
                  : f === "all"
                    ? "All tests"
                    : f === "failed"
                      ? "Failed"
                      : "Flaky"}
              </button>
            ))}
          </div>

          <p className="m-0 text-sm text-rino-muted">Ran in {envLine}</p>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {(
              [
                ["Passed", data.before.passed, data.after.passed, data.fixed_count ? `${data.fixed_count} fixed · ${data.regression_count} broken` : null],
                [
                  "Failed",
                  data.before.failed + data.before.error,
                  data.after.failed + data.after.error,
                  null,
                ],
                ["Skipped", data.before.skipped, data.after.skipped, null],
                ["Flaky", data.before.flaky, data.after.flaky, "not counted as bugs"],
                ["Warnings · pylint", data.before.pylint, data.after.pylint, null],
                ["Warnings · bandit", data.before.bandit, data.after.bandit, null],
              ] as const
            ).map(([label, before, after, hint]) => (
              <div
                key={label}
                className="bg-white border border-rino-border rounded-2xl px-4 py-3.5 shadow-card flex flex-col gap-1"
              >
                <span className="text-xs font-semibold text-rino-muted uppercase tracking-wide">
                  {label}
                </span>
                <span className="text-lg font-semibold tracking-tight">
                  {arrow(before, after)}
                </span>
                {hint ? (
                  <span className="text-xs text-rino-muted">{hint}</span>
                ) : null}
              </div>
            ))}
          </div>

          {data.note ? (
            <p
              className={`m-0 text-sm rounded-xl px-4 py-3 border ${
                data.regression_count > 0
                  ? "bg-[#FEF2F2] border-[#FECACA] text-[#7F1D1D]"
                  : "bg-[#F0FDF4] border-[#BBF7D0] text-[#14532D]"
              }`}
            >
              <b>
                {data.regression_count > 0
                  ? `${data.regression_count} regression${data.regression_count === 1 ? "" : "s"} found.`
                  : "Looking good."}
              </b>{" "}
              {data.note}
              {data.finding_id ? (
                <>
                  {" "}
                  <Link
                    href={`/app/review?run=${data.run_id}&finding=${data.finding_id}`}
                    className="text-rino-indigo"
                  >
                    Open Code Review ›
                  </Link>
                </>
              ) : null}
            </p>
          ) : null}

          <div className="bg-white border border-rino-border rounded-2xl shadow-card overflow-hidden">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-rino-muted border-b border-rino-border bg-[#FAFAF9]">
                  <th className="px-4 py-3 font-semibold">Test</th>
                  <th className="px-4 py-3 font-semibold w-[100px]">Before</th>
                  <th className="px-4 py-3 font-semibold w-[110px]">
                    After fix
                  </th>
                  <th className="px-4 py-3 font-semibold w-[90px]">Duration</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.length === 0 ? (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-4 py-8 text-center text-rino-muted"
                    >
                      No tests match this filter.
                    </td>
                  </tr>
                ) : (
                  visibleRows.map((r) => {
                    const open = expanded === r.key;
                    const regress = r.tag === "regression";
                    return (
                      <Fragment key={r.key}>
                        <tr
                          className={`border-b border-[#F0EFED] cursor-pointer ${
                            regress ? "bg-[#FEF2F2]" : "hover:bg-[#FAFAF9]"
                          }`}
                          onClick={() =>
                            setExpanded(open ? null : r.key)
                          }
                        >
                          <td className="px-4 py-3 font-mono text-xs align-top">
                            <div className="flex flex-col gap-1">
                              <span>{r.key}</span>
                              {r.tag === "fixed" ? (
                                <span className="text-[11px] font-sans font-semibold text-[#15803D] uppercase tracking-wide">
                                  Original failing test · now passes
                                </span>
                              ) : null}
                              {regress ? (
                                <span className="text-[11px] font-sans font-semibold text-[#B91C1C] uppercase tracking-wide">
                                  Regression · passed before, fails after
                                </span>
                              ) : null}
                            </div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            {statusPill(r.before_status)}
                          </td>
                          <td className="px-4 py-3 align-top">
                            {statusPill(r.after_status)}
                          </td>
                          <td className="px-4 py-3 align-top text-rino-muted tabular-nums">
                            {r.duration_seconds != null
                              ? `${r.duration_seconds.toFixed(2)}s`
                              : "—"}
                          </td>
                        </tr>
                        {open ? (
                          <tr
                            className={regress ? "bg-[#FEF2F2]" : "bg-[#FAFAF9]"}
                          >
                            <td colSpan={4} className="px-4 py-3">
                              <div className="grid gap-3 md:grid-cols-2">
                                <pre className="m-0 p-3 rounded-[10px] bg-white border border-rino-border font-mono text-xs whitespace-pre-wrap overflow-x-auto max-h-48">
                                  {r.before_message
                                    ? `Before:\n${r.before_message}`
                                    : "Before: (no output)"}
                                </pre>
                                <pre className="m-0 p-3 rounded-[10px] bg-white border border-rino-border font-mono text-xs whitespace-pre-wrap overflow-x-auto max-h-48">
                                  {r.after_message
                                    ? `After:\n${r.after_message}`
                                    : "After: (no output)"}
                                </pre>
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
            {filter === "changed" &&
            data.rows.some((r) => r.tag === "unchanged") ? (
              <p className="m-0 px-4 py-3 text-xs text-rino-muted border-t border-rino-border">
                … {data.rows.filter((r) => r.tag === "unchanged").length} more
                unchanged · switch Show to All tests
              </p>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
