"use client";

import { useCallback, useEffect, useState } from "react";

type RepoSummary = {
  id: string;
  github_full_name: string;
  default_branch: string;
  status: string;
  test_env: string | null;
  sandbox_ready: boolean;
};

type RunStep = {
  id: string;
  name: string;
  status: string;
  exit_code: number | null;
  log_text: string | null;
};

type TestResult = {
  id: string;
  case_name: string;
  classname: string | null;
  status: string;
  message: string | null;
  duration_seconds: number | null;
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
  steps: RunStep[];
  test_results: TestResult[];
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

export function SandboxRunPanel() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [repoId, setRepoId] = useState("");
  const [branch, setBranch] = useState("main");
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadRepos = useCallback(async () => {
    const list = await api<RepoSummary[]>("/api/developer/repos");
    setRepos(list);
    const ready = list.find((r) => r.sandbox_ready);
    if (ready) {
      setRepoId((prev) => prev || ready.id);
      setBranch(ready.default_branch || "main");
    }
  }, []);

  useEffect(() => {
    loadRepos().catch((e: Error) => setError(e.message));
  }, [loadRepos]);

  useEffect(() => {
    if (!run || ["succeeded", "failed", "timed_out", "cancelled"].includes(run.status)) {
      return;
    }
    const t = setInterval(() => {
      api<AnalysisRun>(`/api/developer/runs/${run.id}`)
        .then(setRun)
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [run]);

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

  async function startRun() {
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
      setError(e instanceof Error ? e.message : "Failed to start run");
    } finally {
      setBusy(false);
    }
  }

  const sandboxRepos = repos.filter((r) => r.sandbox_ready);

  return (
    <section className="bg-white border border-rino-border rounded-2xl p-5 flex flex-col gap-4">
      <div>
        <h2 className="m-0 text-[15px] font-semibold">Sandbox test run</h2>
        <p className="mt-1 mb-0 text-sm text-rino-muted">
          Step 3 — runs setup + pytest with JUnit in a Docker sandbox (no
          lint/LLM yet).
        </p>
      </div>

      {error ? (
        <p className="m-0 text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
          {error}
        </p>
      ) : null}

      {sandboxRepos.length === 0 ? (
        <div className="flex flex-col gap-3">
          <p className="m-0 text-sm text-rino-muted">
            No sandbox-configured repos yet. Admins can seed the local{" "}
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
        </div>
      ) : (
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
              }}
            >
              {sandboxRepos.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.github_full_name}
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
            onClick={startRun}
            disabled={busy || !repoId}
            className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-rino-indigo bg-rino-indigo text-white font-semibold text-sm hover:bg-rino-indigoDark disabled:opacity-50"
          >
            {busy ? "Starting…" : "Run sandbox tests"}
          </button>
        </div>
      )}

      {run ? (
        <div className="flex flex-col gap-3 border-t border-[#F0EFED] pt-4">
          <div className="flex flex-wrap gap-3 items-center text-sm">
            <span className="font-semibold capitalize">Status: {run.status}</span>
            <span className="text-rino-muted font-mono text-xs">
              {run.id.slice(0, 8)}
            </span>
            {run.commit_sha ? (
              <span className="font-mono text-xs text-rino-muted">
                {run.commit_sha.slice(0, 7)}
              </span>
            ) : null}
            <span className="text-rino-muted">
              {run.tests_passed} passed · {run.tests_failed} failed ·{" "}
              {run.tests_errors} errors · {run.tests_skipped} skipped
            </span>
          </div>
          {run.error_message ? (
            <p className="m-0 text-sm text-[#C2410C]">{run.error_message}</p>
          ) : null}
          <div className="flex flex-col gap-1">
            {run.steps.map((s) => (
              <div
                key={s.id}
                className="text-sm flex gap-2 items-baseline font-mono"
              >
                <span className="text-rino-muted w-28">{s.name}</span>
                <span className="capitalize">{s.status}</span>
                {s.exit_code != null ? (
                  <span className="text-rino-muted">exit {s.exit_code}</span>
                ) : null}
              </div>
            ))}
          </div>
          {run.test_results.length > 0 ? (
            <ul className="m-0 pl-5 text-sm flex flex-col gap-1">
              {run.test_results.map((t) => (
                <li key={t.id}>
                  <span
                    className={
                      t.status === "passed"
                        ? "text-[#15803D]"
                        : t.status === "skipped"
                          ? "text-rino-muted"
                          : "text-[#B91C1C]"
                    }
                  >
                    {t.status}
                  </span>{" "}
                  <span className="font-mono">
                    {t.classname ? `${t.classname}::` : ""}
                    {t.case_name}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
