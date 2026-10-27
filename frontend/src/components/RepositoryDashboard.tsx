"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type RepoSummary = {
  id: string;
  github_full_name: string;
  default_branch: string;
  status: string;
  test_env: string | null;
  sandbox_ready: boolean;
  analysis_ready?: boolean;
};

type RunStep = {
  id: string;
  name: string;
  status: string;
  exit_code: number | null;
  log_text: string | null;
  sort_order: number;
};

type Finding = {
  id: string;
  source: string;
  rule_id: string | null;
  file: string | null;
  line: number | null;
  message: string | null;
  severity: "critical" | "high" | "medium" | "low";
  category: string;
  is_code_bug: boolean;
  needs_attention: boolean;
  issue_status: string;
  fix_status: string;
  action_tag: string | null;
  fingerprint: string;
  root_cause: string | null;
  github_issue_number: number | null;
  github_issue_url: string | null;
};

type FindingSummary = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  setup_failed: number;
  environment: number;
  flaky: number;
  needs_attention: number;
  code_bugs: number;
};

type AnalysisRun = {
  id: string;
  repository_id: string;
  repository_full_name: string | null;
  branch: string;
  status: string;
  error_message: string | null;
  tests_total: number;
  tests_passed: number;
  tests_failed: number;
  tests_errors: number;
  tests_skipped: number;
  commit_sha: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  steps: RunStep[];
  findings: Finding[];
  summary: FindingSummary | null;
};

const STEP_LABELS: Record<string, string> = {
  clone: "Clone",
  setup: "Setup",
  test: "Run tests",
  push_branch: "Push rino/ branch",
  trigger_workflow: "Trigger workflow",
  discover_run: "Discover Actions run",
  poll_workflow: "Poll workflow",
  download_artifact: "Download JUnit artifact",
  parse_junit: "Parse JUnit",
  lint: "Run pylint & bandit",
  triage: "Triage",
  explain: "Explain root cause",
};

function repoReady(r: RepoSummary) {
  return Boolean(r.analysis_ready ?? r.sandbox_ready);
}

const FUTURE_STEPS = ["Suggest fix", "Re-run tests", "Awaiting approval"];

function apiBase() {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
    /\/$/,
    ""
  );
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
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

function sevClass(sev: string) {
  switch (sev) {
    case "critical":
      return "bg-[#FEF2F2] text-[#B91C1C]";
    case "high":
      return "bg-[#FFF7ED] text-[#C2410C]";
    case "medium":
      return "bg-[#FEFCE8] text-[#A16207]";
    default:
      return "bg-[#F5F5F4] text-[#57534E]";
  }
}

function envLabel(env: string | null) {
  if (env === "rino_sandbox") return "Rino sandbox";
  if (env === "github_actions") return "GitHub Actions";
  if (env === "dev_instance") return "Dev instance";
  return "Not configured";
}

function issueLabel(f: Finding) {
  if (f.github_issue_number != null) {
    const label = `#${f.github_issue_number}`;
    if (f.github_issue_url?.startsWith("http")) {
      return label;
    }
    return `${label} (${f.issue_status})`;
  }
  if (f.issue_status === "awaiting_confirm") return "Awaiting confirm";
  if (f.issue_status === "none") return "—";
  return f.issue_status;
}

function fixLabel(status: string) {
  if (status === "none") return "—";
  return status;
}

function elapsed(run: AnalysisRun | null) {
  if (!run?.started_at) return null;
  const start = new Date(run.started_at).getTime();
  const end = run.finished_at
    ? new Date(run.finished_at).getTime()
    : Date.now();
  const sec = Math.max(0, Math.round((end - start) / 1000));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")} elapsed`;
}

export function RepositoryDashboard() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [repoId, setRepoId] = useState("");
  const [branch, setBranch] = useState("main");
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [recent, setRecent] = useState<AnalysisRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sevFilter, setSevFilter] = useState("all");
  const [toolFilter, setToolFilter] = useState("all");
  const [, setTick] = useState(0);

  const selected = repos.find((r) => r.id === repoId) || null;

  const loadRepos = useCallback(async () => {
    const list = await api<RepoSummary[]>("/api/developer/repos");
    setRepos(list);
    const ready = list.find((r) => repoReady(r));
    if (ready) {
      setRepoId((prev) => prev || ready.id);
      setBranch((prev) => prev || ready.default_branch || "main");
    }
  }, []);

  const loadRecent = useCallback(async (id: string) => {
    if (!id) {
      setRecent([]);
      return;
    }
    const list = await api<AnalysisRun[]>(
      `/api/developer/runs?repository_id=${id}`
    );
    setRecent(list);
  }, []);

  useEffect(() => {
    loadRepos().catch((e: Error) => setError(e.message));
  }, [loadRepos]);

  useEffect(() => {
    if (repoId) {
      loadRecent(repoId).catch(() => undefined);
    }
  }, [repoId, loadRecent]);

  useEffect(() => {
    if (!run || ["succeeded", "failed", "timed_out", "cancelled"].includes(run.status)) {
      return;
    }
    const t = setInterval(() => {
      api<AnalysisRun>(`/api/developer/runs/${run.id}`)
        .then((r) => {
          setRun(r);
          setTick((n) => n + 1);
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [run]);

  useEffect(() => {
    if (run && ["succeeded", "failed", "timed_out", "cancelled"].includes(run.status)) {
      loadRecent(run.repository_id).catch(() => undefined);
    }
  }, [run, loadRecent]);

  async function seedSample() {
    setBusy(true);
    setError(null);
    try {
      await api("/api/admin/repos/seed-local-sample", { method: "POST" });
      await loadRepos();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not seed sample (Admin role required)"
      );
    } finally {
      setBusy(false);
    }
  }

  async function startAnalysis() {
    if (!repoId) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api<AnalysisRun>(
        `/api/developer/repos/${repoId}/runs`,
        {
          method: "POST",
          body: JSON.stringify({ branch }),
        }
      );
      setRun(created);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start analysis");
    } finally {
      setBusy(false);
    }
  }

  const summary = run?.summary;
  const codeFindings = useMemo(() => {
    const list = (run?.findings || []).filter((f) => f.is_code_bug);
    return list.filter((f) => {
      if (sevFilter !== "all" && f.severity !== sevFilter) return false;
      if (toolFilter !== "all" && f.source !== toolFilter) return false;
      return true;
    });
  }, [run, sevFilter, toolFilter]);

  const steps = [...(run?.steps || [])].sort(
    (a, b) => a.sort_order - b.sort_order
  );

  return (
    <div className="flex flex-col gap-6">
      {error ? (
        <p className="m-0 text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
          {error}
        </p>
      ) : null}

      {repos.filter((r) => repoReady(r)).length === 0 ? (
        <section className="bg-white border border-rino-border rounded-2xl p-5 flex flex-col gap-3">
          <p className="m-0 text-sm text-rino-muted">
            No analysis-ready repos yet. Configure Sandbox or GitHub Actions in
            Admin setup, or seed the local{" "}
            <span className="font-mono">junit-demo</span> fixture:
          </p>
          <button
            type="button"
            onClick={seedSample}
            disabled={busy}
            className="self-start inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-rino-indigo bg-rino-indigo text-white font-semibold text-sm hover:bg-rino-indigoDark disabled:opacity-50"
          >
            Seed local samples (Admin)
          </button>
        </section>
      ) : (
        <section className="bg-white border border-rino-border rounded-2xl p-5 flex flex-col gap-4 shadow-card">
          <div className="flex flex-wrap gap-3 items-end">
            <label className="flex flex-col gap-1.5 min-w-[220px]">
              <span className="text-xs font-medium text-rino-muted">
                Repository
              </span>
              <select
                className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 text-sm bg-white"
                value={repoId}
                onChange={(e) => {
                  setRepoId(e.target.value);
                  const r = repos.find((x) => x.id === e.target.value);
                  if (r) setBranch(r.default_branch || "main");
                  setRun(null);
                }}
              >
                {repos
                  .filter((r) => repoReady(r))
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.github_full_name} · {envLabel(r.test_env)}
                    </option>
                  ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 min-w-[140px]">
              <span className="text-xs font-medium text-rino-muted">Branch</span>
              <input
                className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 text-sm"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
              />
            </label>
            <button
              type="button"
              onClick={startAnalysis}
              disabled={busy || !repoId}
              className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-rino-indigo bg-rino-indigo text-white font-semibold text-sm hover:bg-rino-indigoDark disabled:opacity-50"
            >
              {busy ? "Starting…" : "Start Analysis"}
            </button>
            <span className="ml-auto text-sm text-rino-muted self-center">
              Test env: {envLabel(selected?.test_env ?? null)}
            </span>
          </div>

          {run ? (
            <div className="flex flex-col gap-2.5 border-t border-[#F0EFED] pt-4">
              <div className="flex justify-between items-baseline gap-3">
                <h2 className="m-0 text-[15px] font-semibold">
                  Run {run.id.slice(0, 8)}
                  <span className="ml-2 font-normal text-rino-muted capitalize">
                    · {run.status}
                  </span>
                </h2>
                <span className="font-mono text-xs text-rino-muted">
                  {elapsed(run)}
                </span>
              </div>
              <div
                className="flex flex-wrap gap-2"
                role="list"
                aria-label="Run progress"
              >
                {steps.map((s) => {
                  const done = s.status === "succeeded";
                  const failed = s.status === "failed";
                  const running =
                    s.status === "running" ||
                    (run.status === "running" && s.status === "pending" &&
                      steps.find((x) => x.status === "running") == null &&
                      steps.filter((x) => x.status === "pending")[0]?.id === s.id);
                  return (
                    <div
                      key={s.id}
                      role="listitem"
                      className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium border ${
                        done
                          ? "bg-[#F0FDF4] border-[#BBF7D0] text-[#15803D]"
                          : failed
                            ? "bg-[#FEF2F2] border-[#FECACA] text-[#B91C1C]"
                            : running
                              ? "bg-rino-indigoSoft border-[#C7D2FE] text-rino-indigo"
                              : "bg-[#FAFAF9] border-rino-border text-rino-muted"
                      }`}
                    >
                      <span
                        className={`w-2 h-2 rounded-full ${
                          done
                            ? "bg-[#16A34A]"
                            : failed
                              ? "bg-[#DC2626]"
                              : running
                                ? "bg-rino-indigo"
                                : "bg-[#D6D3D1]"
                        }`}
                      />
                      {STEP_LABELS[s.name] || s.name}
                    </div>
                  );
                })}
                {FUTURE_STEPS.map((label) => (
                  <div
                    key={label}
                    role="listitem"
                    className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium border bg-[#FAFAF9] border-rino-border text-[#A8A29E]"
                  >
                    <span className="w-2 h-2 rounded-full bg-[#E7E5E4]" />
                    {label}
                  </div>
                ))}
              </div>
              {run.error_message ? (
                <p className="m-0 text-sm text-[#C2410C]">{run.error_message}</p>
              ) : null}
            </div>
          ) : null}
        </section>
      )}

      {run && summary ? (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-3">
            {(
              [
                ["Critical", summary.critical, "#DC2626"],
                ["High", summary.high, "#F97316"],
                ["Medium", summary.medium, "#EAB308"],
                ["Low", summary.low, "#94A3B8"],
              ] as const
            ).map(([label, value, color]) => (
              <div
                key={label}
                className="bg-white border border-rino-border rounded-2xl px-4 py-3.5 flex flex-col gap-1 shadow-card"
              >
                <span className="text-xs font-medium text-rino-muted inline-flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ background: color }}
                  />
                  {label}
                </span>
                <span className="text-2xl font-semibold tracking-tight">
                  {value}
                </span>
              </div>
            ))}
            <div className="bg-white border border-rino-border rounded-2xl px-4 py-3.5 flex flex-col gap-1 shadow-card">
              <span className="text-xs font-medium text-rino-muted">
                Tests passed / failed
              </span>
              <span className="text-2xl font-semibold tracking-tight">
                {run.tests_passed} / {run.tests_failed + run.tests_errors}
              </span>
            </div>
            <div className="bg-white border border-rino-border rounded-2xl px-4 py-3.5 flex flex-col gap-1 shadow-card">
              <span className="text-xs font-medium text-rino-muted">
                Needs attention
              </span>
              <span className="text-2xl font-semibold tracking-tight text-rino-indigo">
                {summary.needs_attention}
              </span>
            </div>
          </div>

          <section className="bg-white border border-rino-border rounded-2xl px-5 py-4 flex flex-col gap-3 shadow-card">
            <div className="flex justify-between items-baseline gap-3">
              <h2 className="m-0 text-[15px] font-semibold">Not code bugs</h2>
              <span className="text-xs text-rino-muted">
                Not counted above · no issues or fixes
              </span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              {(
                [
                  ["Setup failed", summary.setup_failed],
                  ["Environment", summary.environment],
                  ["Flaky", summary.flaky],
                ] as const
              ).map(([label, value]) => (
                <div
                  key={label}
                  className="flex justify-between items-center rounded-xl bg-[#FAFAF9] border border-[#F0EFED] px-3.5 py-2.5"
                >
                  <span className="text-sm text-rino-muted">{label}</span>
                  <b className="text-base">{value}</b>
                </div>
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap justify-between items-center gap-3">
              <h2 className="m-0 text-[15px] font-semibold">
                Findings · Run {run.id.slice(0, 8)}
              </h2>
              <div className="flex gap-2">
                <select
                  className="min-h-9 border border-[#D6D3D1] rounded-[10px] px-2.5 text-sm bg-white"
                  aria-label="Severity filter"
                  value={sevFilter}
                  onChange={(e) => setSevFilter(e.target.value)}
                >
                  <option value="all">All severities</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
                <select
                  className="min-h-9 border border-[#D6D3D1] rounded-[10px] px-2.5 text-sm bg-white"
                  aria-label="Tool filter"
                  value={toolFilter}
                  onChange={(e) => setToolFilter(e.target.value)}
                >
                  <option value="all">All tools</option>
                  <option value="pytest">pytest</option>
                  <option value="pylint">pylint</option>
                  <option value="bandit">bandit</option>
                </select>
              </div>
            </div>
            <div className="overflow-x-auto bg-white border border-rino-border rounded-2xl shadow-card">
              <table className="w-full text-sm border-collapse min-w-[760px]">
                <thead>
                  <tr className="text-left text-xs text-rino-muted border-b border-rino-border">
                    <th className="px-4 py-3 font-medium">Severity</th>
                    <th className="px-4 py-3 font-medium">Tool</th>
                    <th className="px-4 py-3 font-medium">File:line</th>
                    <th className="px-4 py-3 font-medium">Message</th>
                    <th className="px-4 py-3 font-medium">GitHub Issue</th>
                    <th className="px-4 py-3 font-medium">Fix status</th>
                    <th className="px-4 py-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {codeFindings.length === 0 ? (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-4 py-6 text-rino-muted text-center"
                      >
                        No code-bug findings for this filter.
                      </td>
                    </tr>
                  ) : (
                    codeFindings.map((f) => (
                      <tr
                        key={f.id}
                        className="border-b border-[#F0EFED] last:border-0"
                      >
                        <td className="px-4 py-3 align-top">
                          <span
                            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${sevClass(f.severity)}`}
                          >
                            {f.severity}
                          </span>
                          {f.needs_attention && f.action_tag ? (
                            <span className="ml-1.5 text-[11px] font-medium text-[#C2410C]">
                              {f.action_tag}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 align-top font-mono text-xs">
                          {f.source}
                        </td>
                        <td className="px-4 py-3 align-top font-mono text-xs">
                          {f.file
                            ? `${f.file}${f.line != null ? `:${f.line}` : ""}`
                            : "—"}
                        </td>
                        <td className="px-4 py-3 align-top max-w-[320px]">
                          <span className="line-clamp-2">
                            {f.rule_id ? `${f.rule_id}: ` : ""}
                            {f.message || "—"}
                          </span>
                          {f.root_cause ? (
                            <span className="block mt-1 text-xs text-rino-indigo line-clamp-1">
                              {f.root_cause}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 align-top text-rino-muted">
                          {f.github_issue_url?.startsWith("http") ? (
                            <a
                              href={f.github_issue_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {issueLabel(f)}
                            </a>
                          ) : (
                            issueLabel(f)
                          )}
                        </td>
                        <td className="px-4 py-3 align-top text-rino-muted">
                          {fixLabel(f.fix_status)}
                        </td>
                        <td className="px-4 py-3 align-top">
                          {(f.severity === "critical" ||
                            f.severity === "high") && (
                            <a
                              className="inline-flex items-center justify-center min-h-8 px-3 rounded-lg border border-rino-border text-xs font-semibold text-rino-ink hover:bg-[#F5F5F4]"
                              href={`/app/review?run=${run.id}&finding=${f.id}`}
                            >
                              Review
                            </a>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <p className="m-0 text-xs text-rino-muted">
              Open <span className="font-medium">Review</span> for Critical/High
              root-cause and Confirm GitHub Issue. Fix generation is a later
              step.
            </p>
          </section>
        </>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="m-0 text-[15px] font-semibold">Recent runs</h2>
        <div className="overflow-x-auto bg-white border border-rino-border rounded-2xl shadow-card">
          <table className="w-full text-sm border-collapse min-w-[640px]">
            <thead>
              <tr className="text-left text-xs text-rino-muted border-b border-rino-border">
                <th className="px-4 py-3 font-medium">Run ID</th>
                <th className="px-4 py-3 font-medium">Branch</th>
                <th className="px-4 py-3 font-medium">Commit</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Tests</th>
                <th className="px-4 py-3 font-medium">Findings</th>
              </tr>
            </thead>
            <tbody>
              {recent.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-6 text-rino-muted text-center"
                  >
                    No runs yet for this repository.
                  </td>
                </tr>
              ) : (
                recent.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b border-[#F0EFED] last:border-0 hover:bg-[#FAFAF9] cursor-pointer"
                    onClick={() => setRun(r)}
                  >
                    <td className="px-4 py-3 font-mono text-xs">
                      {r.id.slice(0, 8)}
                    </td>
                    <td className="px-4 py-3">{r.branch}</td>
                    <td className="px-4 py-3 font-mono text-xs text-rino-muted">
                      {r.commit_sha ? r.commit_sha.slice(0, 7) : "—"}
                    </td>
                    <td className="px-4 py-3 capitalize">{r.status}</td>
                    <td className="px-4 py-3">
                      {r.tests_passed}/{r.tests_total}
                    </td>
                    <td className="px-4 py-3">
                      {r.summary?.code_bugs ?? r.findings?.filter((f) => f.is_code_bug).length ?? 0}
                    </td>
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
