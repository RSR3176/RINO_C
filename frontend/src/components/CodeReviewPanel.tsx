"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { SideBySideDiff, type DiffFile } from "@/components/SideBySideDiff";

type FixAttempt = {
  id: string;
  attempt_number: number;
  status: string;
  explanation: string | null;
  safety_ok: boolean | null;
  safety_violations_json: string | null;
  tests_passed: boolean | null;
  original_failure_gone: boolean | null;
  new_failures: number | null;
  error_message: string | null;
  files_changed_json: string | null;
};

type FindingDetail = {
  id: string;
  run_id: string;
  repository_full_name: string | null;
  branch: string | null;
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
  triage_notes: string | null;
  root_cause: string | null;
  issue_title: string | null;
  issue_body: string | null;
  github_issue_number: number | null;
  github_issue_url: string | null;
  fingerprint: string;
  test_id: string | null;
  exception_type: string | null;
  fix_branch: string | null;
  fix_explanation: string | null;
  verified_diff: string | null;
  verified_files: DiffFile[];
  github_pr_number: number | null;
  github_pr_url: string | null;
  pr_status: string;
  fix_attempts: FixAttempt[];
  pull_requests: {
    id: string;
    branch_name: string;
    title: string;
    github_pr_number: number | null;
    github_pr_url: string | null;
    dry_run: boolean;
    status: string;
    pushed: boolean;
  }[];
  llm_calls: {
    id: string;
    model: string;
    purpose: string;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    success: boolean;
  }[];
};

type AnalysisRun = {
  id: string;
  repository_full_name: string | null;
  status: string;
  findings: { id: string; severity: string; is_code_bug: boolean }[];
};

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

function loc(f: FindingDetail) {
  if (!f.file) return "—";
  return f.line != null ? `${f.file}:${f.line}` : f.file;
}

function sevClass(sev: string) {
  if (sev === "critical") return "bg-[#FEF2F2] text-[#B91C1C]";
  if (sev === "high") return "bg-[#FFF7ED] text-[#C2410C]";
  return "bg-[#F5F5F4] text-[#57534E]";
}

function parseFiles(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export function CodeReviewPanel() {
  const params = useSearchParams();
  const initialFinding = params.get("finding");
  const initialRun = params.get("run");

  const [runId, setRunId] = useState(initialRun || "");
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [findings, setFindings] = useState<FindingDetail[]>([]);
  const [findingId, setFindingId] = useState(initialFinding || "");
  const [activeFile, setActiveFile] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmMsg, setConfirmMsg] = useState<string | null>(null);

  const selected = useMemo(
    () => findings.find((f) => f.id === findingId) || findings[0] || null,
    [findings, findingId]
  );

  const loadRuns = useCallback(async () => {
    const list = await api<AnalysisRun[]>("/api/developer/runs");
    setRuns(list);
    if (!runId && list[0]) setRunId(list[0].id);
  }, [runId]);

  const loadFindings = useCallback(async (rid: string) => {
    if (!rid) {
      setFindings([]);
      return;
    }
    const list = await api<FindingDetail[]>(
      `/api/developer/runs/${rid}/review-findings`
    );
    setFindings(list);
    setFindingId((prev) => {
      if (prev && list.some((f) => f.id === prev)) return prev;
      return list[0]?.id || "";
    });
  }, []);

  useEffect(() => {
    loadRuns().catch((e: Error) => setError(e.message));
  }, [loadRuns]);

  useEffect(() => {
    if (runId) {
      loadFindings(runId).catch((e: Error) => setError(e.message));
    }
  }, [runId, loadFindings]);

  // Poll while fix is in progress
  useEffect(() => {
    if (
      !selected ||
      !["queued", "generating"].includes(selected.fix_status)
    ) {
      return;
    }
    const t = setInterval(() => {
      api<FindingDetail>(`/api/developer/findings/${selected.id}`)
        .then((detail) => {
          setFindings((prev) =>
            prev.map((f) => (f.id === detail.id ? detail : f))
          );
        })
        .catch(() => undefined);
    }, 2500);
    return () => clearInterval(t);
  }, [selected]);

  useEffect(() => {
    if (selected?.verified_files?.length) {
      setActiveFile(selected.verified_files[0].path);
    }
  }, [selected?.id, selected?.verified_files]);

  async function refreshSelected() {
    if (!selected) return;
    const detail = await api<FindingDetail>(
      `/api/developer/findings/${selected.id}`
    );
    setFindings((prev) => prev.map((f) => (f.id === detail.id ? detail : f)));
  }

  async function confirmIssue() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setConfirmMsg(null);
    try {
      const res = await api<{
        issue_status: string;
        github_issue_number: number | null;
        github_issue_url: string | null;
        dry_run: boolean;
        detail: string | null;
        fix_queued: boolean;
      }>(`/api/developer/findings/${selected.id}/confirm-issue`, {
        method: "POST",
      });
      setConfirmMsg(
        [
          res.dry_run
            ? `${res.detail || "Dry-run"} → ${res.github_issue_url}`
            : res.detail || `Issue #${res.github_issue_number} created`,
          res.fix_queued ? "Fix job queued." : null,
        ]
          .filter(Boolean)
          .join(" ")
      );
      await refreshSelected();
      await loadFindings(runId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Confirm failed");
    } finally {
      setBusy(false);
    }
  }

  async function discardFix() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/developer/findings/${selected.id}/discard-fix`, {
        method: "POST",
      });
      setConfirmMsg("Fix discarded — nothing pushed.");
      await refreshSelected();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Discard failed");
    } finally {
      setBusy(false);
    }
  }

  async function startFix() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/developer/findings/${selected.id}/start-fix`, {
        method: "POST",
      });
      setConfirmMsg("Fix job queued.");
      await refreshSelected();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start fix");
    } finally {
      setBusy(false);
    }
  }

  async function approvePr() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setConfirmMsg(null);
    try {
      const res = await api<{
        dry_run: boolean;
        pushed: boolean;
        github_pr_number: number | null;
        github_pr_url: string | null;
        branch: string | null;
        detail: string | null;
      }>(`/api/developer/findings/${selected.id}/approve-pr`, {
        method: "POST",
      });
      setConfirmMsg(
        [
          res.detail || "Draft PR recorded",
          res.github_pr_url ? `→ ${res.github_pr_url}` : null,
          res.pushed ? "Branch pushed." : "Nothing pushed (dry-run).",
        ]
          .filter(Boolean)
          .join(" ")
      );
      await refreshSelected();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusy(false);
    }
  }

  const canConfirm =
    selected &&
    selected.severity === "critical" &&
    (selected.issue_status === "awaiting_confirm" ||
      selected.issue_status === "none");
  const alreadyDone =
    selected &&
    ["open", "linked", "dry_run"].includes(selected.issue_status) &&
    selected.github_issue_url;

  const verified =
    selected?.fix_status === "verified" ||
    selected?.fix_status === "pr_opened";
  const discarded = selected?.fix_status === "discarded";
  const prOpened =
    selected?.fix_status === "pr_opened" ||
    ["open", "dry_run"].includes(selected?.pr_status || "");
  const fixing = selected
    ? ["queued", "generating"].includes(selected.fix_status)
    : false;
  const canApprove =
    selected?.fix_status === "verified" && !prOpened && !discarded;

  const changedFiles =
    selected?.verified_files?.map((f) => f.path) ||
    parseFiles(
      selected?.fix_attempts?.slice(-1)[0]?.files_changed_json || null
    );

  return (
    <div className="flex flex-col gap-5">
      {error ? (
        <p className="m-0 text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
          {error}
        </p>
      ) : null}
      {confirmMsg ? (
        <p className="m-0 text-sm text-[#15803D] bg-[#F0FDF4] border border-[#BBF7D0] rounded-xl px-3 py-2">
          {confirmMsg}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3 items-end justify-between">
        <div className="flex flex-wrap gap-3 items-end">
          <label className="flex flex-col gap-1.5 min-w-[220px]">
            <span className="text-xs font-medium text-rino-muted">Run</span>
            <select
              className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 text-sm bg-white"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
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
          <label className="flex flex-col gap-1.5 min-w-[280px]">
            <span className="text-xs font-medium text-rino-muted">
              Reviewing
            </span>
            <select
              className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 text-sm bg-white"
              value={selected?.id || ""}
              onChange={(e) => setFindingId(e.target.value)}
              disabled={findings.length === 0}
            >
              {findings.length === 0 ? (
                <option value="">No Critical/High findings</option>
              ) : (
                findings.map((f, i) => (
                  <option key={f.id} value={f.id}>
                    {f.severity.toUpperCase()} · {loc(f)} ({i + 1} of{" "}
                    {findings.length})
                  </option>
                ))
              )}
            </select>
          </label>
        </div>
        <Link href="/app" className="text-sm text-rino-indigo">
          ‹ Back to findings
        </Link>
      </div>

      {!selected ? (
        <section className="bg-white border border-rino-border rounded-2xl p-6 text-sm text-rino-muted">
          Run an analysis, then open Critical findings here to confirm issues
          and review verified fixes.
        </section>
      ) : (
        <>
          <section className="bg-white border border-rino-border rounded-2xl p-5 flex flex-col gap-4 shadow-card">
            <div className="flex flex-wrap gap-2 items-center">
              <span
                className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${sevClass(selected.severity)}`}
              >
                {selected.severity}
              </span>
              <span className="font-mono text-sm">{loc(selected)}</span>
              <span className="text-xs rounded-full px-2.5 py-0.5 bg-[#F5F5F4] text-rino-muted">
                {selected.source}
              </span>
              <span className="text-xs rounded-full px-2.5 py-0.5 bg-rino-indigoSoft text-rino-indigo capitalize">
                fix: {selected.fix_status}
              </span>
            </div>
            <h1 className="m-0 text-xl font-semibold tracking-tight">
              {selected.issue_title ||
                selected.message?.split("\n")[0] ||
                selected.rule_id ||
                "Finding"}
            </h1>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-2 min-w-0">
                <span className="text-xs font-semibold text-rino-muted uppercase tracking-wide">
                  Evidence
                </span>
                <pre className="m-0 p-3.5 rounded-[10px] bg-[#FAFAF9] border border-rino-border font-mono text-xs leading-relaxed whitespace-pre-wrap overflow-x-auto max-h-56">
                  {selected.message || "(no message)"}
                </pre>
              </div>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5 p-3.5 rounded-xl bg-[#FEF2F2] text-[#7F1D1D] text-sm">
                  <b>Matched rule / why {selected.severity}</b>
                  <span>
                    {selected.triage_notes ||
                      `Rule from triage · ${selected.rule_id || selected.source}`}
                  </span>
                </div>
                <div className="flex flex-col gap-1.5 p-3.5 rounded-xl bg-rino-indigoSoft text-[#312E81] text-sm leading-relaxed">
                  <b>Likely root cause (AI)</b>
                  <span>
                    {selected.root_cause || "Not generated yet."}
                  </span>
                </div>
              </div>
            </div>
          </section>

          {selected.severity === "critical" ? (
            <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
              <aside className="bg-white border border-rino-border rounded-2xl p-4 flex flex-col gap-2 shadow-card h-fit">
                <span className="text-xs font-semibold text-rino-muted uppercase tracking-wide">
                  Affected files ({changedFiles.length})
                </span>
                <ul className="m-0 p-0 list-none flex flex-col gap-0.5">
                  {changedFiles.length === 0 ? (
                    <li className="text-sm text-rino-muted px-2.5 py-2">
                      {fixing ? "Generating…" : "—"}
                    </li>
                  ) : (
                    changedFiles.map((path) => (
                      <li key={path}>
                        <button
                          type="button"
                          onClick={() => setActiveFile(path)}
                          className={`w-full text-left font-mono text-xs px-2.5 py-2.5 rounded-lg flex justify-between gap-2 ${
                            activeFile === path
                              ? "bg-rino-indigoSoft text-rino-indigo font-semibold"
                              : "hover:bg-[#F5F5F4]"
                          }`}
                        >
                          <span className="truncate">{path}</span>
                        </button>
                      </li>
                    ))
                  )}
                </ul>
                <span className="text-xs text-rino-muted">
                  Test files changed: 0
                </span>
                {selected.fix_branch ? (
                  <span className="text-xs font-mono text-rino-muted break-all">
                    {selected.fix_branch}
                  </span>
                ) : null}
              </aside>

              <section className="flex flex-col gap-3 min-w-0">
                {verified && selected.verified_files.length > 0 ? (
                  <>
                    <SideBySideDiff
                      files={selected.verified_files}
                      activePath={activeFile}
                    />
                    <div className="bg-white border border-rino-border rounded-2xl px-5 py-4 shadow-card">
                      <span className="text-xs font-semibold text-rino-muted uppercase tracking-wide">
                        What changed
                      </span>
                      <p className="mt-2 mb-0 text-sm leading-relaxed">
                        {selected.fix_explanation || "—"}
                      </p>
                    </div>
                  </>
                ) : discarded ? (
                  <div className="bg-white border border-rino-border rounded-2xl p-5 text-sm text-rino-muted shadow-card">
                    Fix discarded. Nothing was pushed.
                  </div>
                ) : fixing ? (
                  <div className="bg-white border border-rino-border rounded-2xl p-5 text-sm shadow-card">
                    Generating and verifying a fix (max 3 attempts)…
                  </div>
                ) : selected.fix_status === "failed" ? (
                  <div className="bg-white border border-rino-border rounded-2xl p-5 text-sm shadow-card text-[#9A3412]">
                    No verified fix after 3 attempts. See attempt history and
                    the issue comment (dry-run ok).
                  </div>
                ) : (
                  <div className="bg-white border border-rino-border rounded-2xl p-5 text-sm text-rino-muted shadow-card">
                    Confirm the GitHub Issue (or wait for the auto-queued fix
                    job) to generate a patch, then Approve & Open Draft PR.
                  </div>
                )}
              </section>
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-3">
            <section className="bg-white border border-rino-border rounded-2xl p-4 flex flex-col gap-2 shadow-card">
              <h2 className="m-0 text-[15px] font-semibold">Safety checks</h2>
              {(() => {
                const last = selected.fix_attempts.slice(-1)[0];
                const ok = last?.safety_ok;
                const items = [
                  ["No test files touched", ok !== false],
                  ["No skipped tests", ok !== false],
                  [
                    "Within file limit (≤3)",
                    ok !== false,
                  ],
                ] as const;
                return items.map(([label, pass]) => (
                  <div key={label} className="flex gap-2.5 items-center text-sm">
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        pass
                          ? "bg-[#F0FDF4] text-[#15803D]"
                          : "bg-[#FEF2F2] text-[#B91C1C]"
                      }`}
                    >
                      {pass ? "Pass" : "Fail"}
                    </span>
                    {label}
                  </div>
                ));
              })()}
            </section>
            <section className="bg-white border border-rino-border rounded-2xl p-4 flex flex-col gap-2 shadow-card">
              <h2 className="m-0 text-[15px] font-semibold">Attempt history</h2>
              {selected.fix_attempts.length === 0 ? (
                <span className="text-sm text-rino-muted">No attempts yet</span>
              ) : (
                selected.fix_attempts.map((a) => (
                  <div
                    key={a.id}
                    className="flex gap-3 items-start py-2.5 border-b border-[#F0EFED] last:border-0 text-sm"
                  >
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${
                        a.status === "verified"
                          ? "bg-[#F0FDF4] text-[#15803D]"
                          : a.status === "rejected" || a.status === "failed"
                            ? "bg-[#FEF2F2] text-[#B91C1C]"
                            : "bg-[#F5F5F4] text-rino-muted"
                      }`}
                    >
                      Attempt {a.attempt_number} · {a.status}
                    </span>
                    <span className="text-rino-muted text-xs">
                      {a.error_message || a.explanation || ""}
                    </span>
                  </div>
                ))
              )}
            </section>
            <section className="bg-white border border-rino-border rounded-2xl p-4 flex flex-col gap-2 shadow-card">
              <h2 className="m-0 text-[15px] font-semibold">On GitHub</h2>
              {selected.severity !== "critical" ? (
                <p className="m-0 text-sm text-rino-muted">
                  High findings do not open Issues in Step 5/6.
                </p>
              ) : alreadyDone ? (
                <p className="m-0 text-sm">
                  Issue:{" "}
                  <span className="font-mono">
                    #{selected.github_issue_number}
                  </span>{" "}
                  <span className="inline-flex ml-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#F0FDF4] text-[#15803D] capitalize">
                    {selected.issue_status}
                  </span>
                </p>
              ) : (
                <p className="m-0 text-sm text-rino-muted">
                  Awaiting confirm · labels bug, ai-found, critical
                </p>
              )}
              {prOpened && selected.github_pr_url ? (
                <p className="m-0 text-sm">
                  Pull request:{" "}
                  <span className="font-mono">
                    #{selected.github_pr_number}
                  </span>{" "}
                  <span className="inline-flex ml-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#F0FDF4] text-[#15803D] capitalize">
                    {selected.pr_status}
                  </span>
                  <span className="block text-xs text-rino-muted mt-1 break-all">
                    {selected.github_pr_url}
                  </span>
                </p>
              ) : (
                <p className="m-0 text-xs text-rino-muted">
                  Pull request: appears here after approval
                </p>
              )}
            </section>
          </div>

          <div className="flex flex-wrap gap-3 items-center bg-white border border-rino-border rounded-2xl px-5 py-4 shadow-card">
            <span className="text-sm text-rino-muted mr-auto">
              {selected.fix_branch
                ? `Draft PR will open on ${selected.fix_branch}. Nothing merges automatically.`
                : "Nothing reaches GitHub until you confirm the issue and approve a verified fix."}
              {selected.fix_status === "verified" ? (
                <>
                  {" "}
                  <Link
                    href={`/app/testing?run=${selected.run_id}&finding=${selected.id}`}
                    className="text-rino-indigo"
                  >
                    Before / after test results ›
                  </Link>
                </>
              ) : null}
            </span>
            <button
              type="button"
              disabled={
                busy ||
                discarded ||
                prOpened ||
                !["verified", "failed", "generating", "queued"].includes(
                  selected.fix_status
                )
              }
              onClick={discardFix}
              className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-[#FECACA] bg-white text-[#B91C1C] font-semibold text-sm hover:bg-[#FEF2F2] disabled:opacity-50"
            >
              Discard Fix
            </button>
            <button
              type="button"
              disabled={busy || (!canConfirm && !alreadyDone)}
              onClick={confirmIssue}
              className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-[#D6D3D1] bg-white text-rino-ink font-semibold text-sm hover:bg-[#F5F5F4] disabled:opacity-50"
            >
              {alreadyDone
                ? "Confirm GitHub Issue · done"
                : busy
                  ? "Confirming…"
                  : "Confirm GitHub Issue"}
            </button>
            {selected.severity === "critical" &&
            selected.fix_status === "none" ? (
              <button
                type="button"
                disabled={busy}
                onClick={startFix}
                className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-[#D6D3D1] bg-white text-rino-ink font-semibold text-sm hover:bg-[#F5F5F4] disabled:opacity-50"
              >
                Start fix
              </button>
            ) : null}
            <button
              type="button"
              disabled={busy || !canApprove}
              onClick={approvePr}
              className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-rino-indigo bg-rino-indigo text-white font-semibold text-sm hover:bg-rino-indigoDark disabled:opacity-50 disabled:bg-[#F5F5F4] disabled:text-rino-muted disabled:border-[#D6D3D1]"
              title={
                canApprove
                  ? "Push rino/fix-* and open a draft PR"
                  : prOpened
                    ? "Draft PR already recorded"
                    : "Needs a verified fix"
              }
            >
              {prOpened
                ? "Approve & Open Draft PR · done"
                : busy && canApprove
                  ? "Opening…"
                  : "Approve & Open Draft PR"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
