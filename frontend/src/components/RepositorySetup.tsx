"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { User } from "@/lib/api";
import {
  connectRepo,
  fetchAvailableRepos,
  fetchInstallation,
  fetchInstallUrl,
  fetchRepos,
  fetchWorkflows,
  saveTestConfig,
  testConnection,
  type AvailableRepo,
  type GithubInstallation,
  type Repository,
  type TestEnv,
  type WorkflowOption,
} from "@/lib/adminApi";

const PYTHON_VERSIONS = ["3.12", "3.11", "3.10"];

function statusPill(repo: Repository) {
  const label =
    repo.status_detail ||
    (repo.status === "ready"
      ? "Ready"
      : repo.status === "access_revoked"
        ? "Access revoked"
        : "Needs attention");
  const cls =
    repo.status === "ready"
      ? "bg-[#F0FDF4] text-[#15803D]"
      : repo.status === "access_revoked"
        ? "bg-[#FEF2F2] text-[#B91C1C]"
        : "bg-[#FFF7ED] text-[#C2410C]";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}

function EnvIcon({ kind }: { kind: TestEnv }) {
  if (kind === "github_actions") {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <circle cx="12" cy="12" r="9" />
        <path d="M10 8l6 4-6 4z" />
      </svg>
    );
  }
  if (kind === "dev_instance") {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <rect x="3" y="4" width="18" height="12" rx="2" />
        <path d="M8 20h8M12 16v4" />
      </svg>
    );
  }
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
      <path d="M4 7.5l8 4.5 8-4.5M12 12v9" />
    </svg>
  );
}

export function RepositorySetup({ user }: { user: User }) {
  const [installation, setInstallation] = useState<GithubInstallation | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [available, setAvailable] = useState<AvailableRepo[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [workflows, setWorkflows] = useState<WorkflowOption[]>([]);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Draft form state
  const [testEnv, setTestEnv] = useState<TestEnv | null>(null);
  const [workflowFile, setWorkflowFile] = useState("");
  const [setupCommand, setSetupCommand] = useState("pip install -r requirements.txt");
  const [testCommand, setTestCommand] = useState("pytest");
  const [pythonVersion, setPythonVersion] = useState("3.11");
  const [sharedDev, setSharedDev] = useState(true);
  const [dirty, setDirty] = useState(false);

  const selected = useMemo(
    () => repos.find((r) => r.id === selectedId) || null,
    [repos, selectedId]
  );

  const loadCore = useCallback(async () => {
    setError(null);
    const [inst, list] = await Promise.all([fetchInstallation(), fetchRepos()]);
    setInstallation(inst);
    setRepos(list);
    setSelectedId((prev) => {
      if (prev && list.some((r) => r.id === prev)) return prev;
      return list[0]?.id ?? null;
    });
  }, []);

  useEffect(() => {
    loadCore().catch((e: Error) => setError(e.message));
  }, [loadCore]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("installed") === "1") {
      setNotice("GitHub App installation saved.");
      window.history.replaceState({}, "", "/admin");
    }
    const err = params.get("error");
    if (err) {
      setError(`GitHub App setup issue: ${err.replaceAll("_", " ")}`);
      window.history.replaceState({}, "", "/admin");
    }
  }, []);

  useEffect(() => {
    if (!selected) return;
    const cfg = selected.test_config;
    setTestEnv(cfg?.test_env ?? null);
    setWorkflowFile(cfg?.workflow_file || ".github/workflows/test.yml");
    setSetupCommand(cfg?.setup_command || "pip install -r requirements.txt");
    setTestCommand(cfg?.test_command || "pytest");
    setPythonVersion(cfg?.python_version || "3.11");
    setSharedDev(cfg?.shared_dev_instance ?? true);
    setDirty(false);
    fetchWorkflows(selected.id)
      .then(setWorkflows)
      .catch(() => setWorkflows([]));
  }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onInstall() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await fetchInstallUrl();
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start install");
      setBusy(false);
    }
  }

  async function openAdd() {
    setShowAdd(true);
    setError(null);
    try {
      setAvailable(await fetchAvailableRepos());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not list repos");
    }
  }

  async function onConnect(repo: AvailableRepo) {
    setBusy(true);
    setError(null);
    try {
      const connected = await connectRepo(repo.github_repo_id, repo.full_name);
      await loadCore();
      setSelectedId(connected.id);
      setShowAdd(false);
      setNotice(`Connected ${connected.github_full_name}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not connect repo");
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await saveTestConfig(selected.id, {
        test_env: testEnv,
        workflow_file: workflowFile,
        setup_command: setupCommand,
        test_command: testCommand,
        python_version: pythonVersion,
        shared_dev_instance: sharedDev,
      });
      setRepos((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      setDirty(false);
      setNotice("Setup saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function onTest() {
    if (!selected) return;
    setTesting(true);
    setError(null);
    try {
      if (dirty) {
        await onSave();
      }
      const result = await testConnection(selected.id);
      setRepos((prev) =>
        prev.map((r) => (r.id === result.repository.id ? result.repository : r))
      );
      setNotice(result.detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test connection failed");
    } finally {
      setTesting(false);
    }
  }

  function pickEnv(env: TestEnv) {
    setTestEnv(env);
    setDirty(true);
  }

  const isRunner =
    testEnv === "github_actions" || testEnv === "dev_instance";
  const isSandbox = testEnv === "rino_sandbox";
  const isDev = testEnv === "dev_instance";

  return (
    <>
      <div className="flex flex-wrap gap-3 items-start justify-between">
        <div>
          <h1 className="m-0 text-[26px] font-bold tracking-tight">
            Repository Setup
          </h1>
          <p className="mt-2 mb-0 text-rino-muted">
            Connect repos and tell Rino where their tests run.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          {installation?.installed ? (
            <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#F0FDF4] text-[#15803D]">
              <span className="w-1.5 h-1.5 rounded-full bg-current" />
              GitHub App installed · {installation.account_login}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#FFF7ED] text-[#C2410C]">
              <span className="w-1.5 h-1.5 rounded-full bg-current" />
              GitHub App not installed
            </span>
          )}
          <button
            type="button"
            className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-[#D6D3D1] bg-white font-semibold text-sm hover:border-[#A8A29E]"
            onClick={onInstall}
            disabled={busy}
          >
            Install GitHub App
          </button>
        </div>
      </div>

      {error ? (
        <p className="m-0 text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="m-0 text-sm text-[#3730A3] bg-[#EEF2FF] border border-[#E0E7FF] rounded-xl px-3 py-2">
          {notice}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-5 items-start">
        <section
          className="bg-white border border-rino-border rounded-2xl p-5 flex flex-col gap-1.5 shadow-[0_1px_2px_rgba(28,25,23,.04)] flex-[1_1_260px] max-w-[320px]"
          aria-label="Connected repositories"
        >
          <div className="flex items-center justify-between px-1 pb-2">
            <h2 className="m-0 text-[15px] font-semibold">Connected repos</h2>
            <button
              type="button"
              className="min-h-8 px-2 rounded-[10px] text-sm font-medium text-rino-muted hover:text-rino-ink"
              onClick={openAdd}
              disabled={!installation?.installed || busy}
            >
              + Add
            </button>
          </div>
          {repos.length === 0 ? (
            <p className="m-0 text-sm text-rino-muted px-1 py-3">
              No repos connected yet. Install the GitHub App, then click + Add.
            </p>
          ) : (
            repos.map((repo) => {
              const on = repo.id === selectedId;
              return (
                <button
                  key={repo.id}
                  type="button"
                  onClick={() => setSelectedId(repo.id)}
                  className={`flex flex-col gap-1.5 text-left px-3.5 py-3 rounded-xl border ${
                    on
                      ? "bg-rino-indigoSoft border-[#C7D2FE]"
                      : "border-transparent hover:bg-[#FAFAF9]"
                  }`}
                >
                  <span className="font-mono text-[13px] font-semibold">
                    {repo.github_full_name}
                  </span>
                  <span className="self-start">{statusPill(repo)}</span>
                </button>
              );
            })
          )}
        </section>

        <section
          className="bg-white border border-rino-border rounded-2xl p-5 flex flex-col gap-5 shadow-[0_1px_2px_rgba(28,25,23,.04)] flex-[999_1_560px] min-w-0"
          aria-label="Setup form"
        >
          {!selected ? (
            <p className="m-0 text-sm text-rino-muted">
              Select a connected repository to configure where its tests run.
            </p>
          ) : (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <span className="text-xs text-rino-muted">
                    {selected.github_full_name}
                  </span>
                  <h2 className="m-0 text-lg font-semibold">
                    Where do your tests run?
                  </h2>
                </div>
                {statusPill(selected)}
              </div>

              <div
                className="grid gap-3"
                style={{
                  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                }}
                role="radiogroup"
                aria-label="Test environment"
              >
                {(
                  [
                    {
                      id: "github_actions" as TestEnv,
                      title: "GitHub Actions (CI)",
                      desc: "Runs your existing workflow on GitHub's runners.",
                    },
                    {
                      id: "dev_instance" as TestEnv,
                      title: "Dev instance",
                      desc: "Your own machine, via a self-hosted runner.",
                    },
                    {
                      id: "rino_sandbox" as TestEnv,
                      title: "Rino sandbox (Docker)",
                      desc: "A clean container Rino builds from your commands.",
                    },
                  ] as const
                ).map((opt) => {
                  const on = testEnv === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => pickEnv(opt.id)}
                      className={`flex flex-col items-start gap-2 text-left p-4 rounded-[14px] min-h-[120px] border ${
                        on
                          ? "border-2 border-rino-indigo bg-[#FAFAFF] p-[15px]"
                          : "border-rino-border bg-white hover:border-[#A5B4FC]"
                      }`}
                    >
                      <span
                        className={`w-[34px] h-[34px] rounded-[10px] flex items-center justify-center ${
                          on
                            ? "bg-rino-indigoSoft text-rino-indigo"
                            : "bg-[#F5F5F4] text-[#44403C]"
                        }`}
                      >
                        <EnvIcon kind={opt.id} />
                      </span>
                      <span className="font-semibold">{opt.title}</span>
                      <span className="text-xs text-rino-muted leading-relaxed">
                        {opt.desc}
                      </span>
                    </button>
                  );
                })}
              </div>

              {isRunner ? (
                <div className="flex flex-col gap-3.5 p-[18px] rounded-[14px] bg-[#FAFAF9] border border-rino-border">
                  <h3 className="m-0 text-sm font-semibold">
                    {isDev ? "Dev instance" : "GitHub Actions (CI)"}
                  </h3>
                  <div
                    className="grid gap-4"
                    style={{
                      gridTemplateColumns:
                        "repeat(auto-fit, minmax(240px, 1fr))",
                    }}
                  >
                    <label className="flex flex-col gap-1.5 min-w-0">
                      <span className="text-xs font-medium text-rino-muted">
                        Workflow file
                      </span>
                      <select
                        className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 font-mono text-sm bg-white"
                        value={workflowFile}
                        onChange={(e) => {
                          setWorkflowFile(e.target.value);
                          setDirty(true);
                        }}
                      >
                        {workflows.map((w) => (
                          <option key={w.path} value={w.path}>
                            {w.path}
                          </option>
                        ))}
                        {!workflows.some((w) => w.path === workflowFile) &&
                        workflowFile ? (
                          <option value={workflowFile}>{workflowFile}</option>
                        ) : null}
                      </select>
                    </label>
                    <div className="flex items-end gap-2.5 flex-wrap">
                      <button
                        type="button"
                        className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-[#D6D3D1] bg-white font-semibold text-sm"
                        onClick={onTest}
                        disabled={testing || busy}
                      >
                        {testing ? "Testing…" : "Test connection"}
                      </button>
                      {selected.test_config?.last_check_ok === true ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-[#F0FDF4] text-[#15803D]">
                          <span className="w-1.5 h-1.5 rounded-full bg-current" />
                          Connected
                          {selected.test_config.last_check_latency_ms != null
                            ? ` · ${selected.test_config.last_check_latency_ms}ms`
                            : ""}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <p className="m-0 text-[13px] text-[#3730A3] bg-[#EEF2FF] border border-[#E0E7FF] rounded-xl px-4 py-3">
                    The workflow needs a manual trigger. Add{" "}
                    <span className="font-mono">on: workflow_dispatch</span> to
                    it so Rino can start runs.
                  </p>
                  {isDev ? (
                    <p className="m-0 text-[13px] text-rino-muted">
                      Runner label:{" "}
                      <span className="font-mono">self-hosted, rino-dev</span>
                    </p>
                  ) : null}
                </div>
              ) : null}

              {isSandbox ? (
                <div className="flex flex-col gap-3.5 p-[18px] rounded-[14px] bg-[#FAFAF9] border border-rino-border">
                  <h3 className="m-0 text-sm font-semibold">
                    Rino sandbox (Docker)
                  </h3>
                  <div
                    className="grid gap-4"
                    style={{
                      gridTemplateColumns:
                        "repeat(auto-fit, minmax(240px, 1fr))",
                    }}
                  >
                    <label className="flex flex-col gap-1.5">
                      <span className="text-xs font-medium text-rino-muted">
                        Setup command
                      </span>
                      <input
                        className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 font-mono text-sm"
                        value={setupCommand}
                        onChange={(e) => {
                          setSetupCommand(e.target.value);
                          setDirty(true);
                        }}
                      />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-xs font-medium text-rino-muted">
                        Test command
                      </span>
                      <input
                        className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 font-mono text-sm"
                        value={testCommand}
                        onChange={(e) => {
                          setTestCommand(e.target.value);
                          setDirty(true);
                        }}
                      />
                    </label>
                    <label className="flex flex-col gap-1.5">
                      <span className="text-xs font-medium text-rino-muted">
                        Python version
                      </span>
                      <select
                        className="min-h-10 border border-[#D6D3D1] rounded-[10px] px-3 text-sm bg-white"
                        value={pythonVersion}
                        onChange={(e) => {
                          setPythonVersion(e.target.value);
                          setDirty(true);
                        }}
                      >
                        {PYTHON_VERSIONS.map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="flex items-end">
                      <button
                        type="button"
                        className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-[#D6D3D1] bg-white font-semibold text-sm"
                        onClick={onTest}
                        disabled={testing || busy}
                      >
                        {testing ? "Testing…" : "Test connection"}
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}

              <label className="flex gap-2.5 items-start text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 accent-[#4338CA] w-4 h-4"
                  checked={sharedDev}
                  onChange={(e) => {
                    setSharedDev(e.target.checked);
                    setDirty(true);
                  }}
                />
                <span>
                  Dev instance is shared — run one job at a time
                  <br />
                  <span className="text-xs text-rino-muted">
                    Queues runs instead of starting them in parallel.
                  </span>
                </span>
              </label>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#F0EFED] pt-4">
                <span className="text-[13px] text-rino-muted">
                  {selected.test_config?.last_checked_at
                    ? `Last checked ${new Date(
                        selected.test_config.last_checked_at
                      ).toLocaleString()}`
                    : "Not checked yet"}{" "}
                  · setup changes are logged in the Audit log
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="min-h-10 px-[18px] rounded-[10px] text-sm font-medium text-rino-muted"
                    onClick={() => {
                      if (selected) setSelectedId(selected.id);
                      setDirty(false);
                      // re-sync from selected via effect by forcing id refresh
                      const cfg = selected.test_config;
                      setTestEnv(cfg?.test_env ?? null);
                      setWorkflowFile(
                        cfg?.workflow_file || ".github/workflows/test.yml"
                      );
                      setSetupCommand(
                        cfg?.setup_command || "pip install -r requirements.txt"
                      );
                      setTestCommand(cfg?.test_command || "pytest");
                      setPythonVersion(cfg?.python_version || "3.11");
                      setSharedDev(cfg?.shared_dev_instance ?? true);
                    }}
                    disabled={!dirty || busy}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center justify-center min-h-10 px-[18px] rounded-[10px] border border-rino-indigo bg-rino-indigo text-white font-semibold text-sm hover:bg-rino-indigoDark disabled:opacity-50"
                    onClick={onSave}
                    disabled={!dirty || busy}
                  >
                    Save
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      {showAdd ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="bg-white rounded-2xl border border-rino-border shadow-card w-full max-w-lg max-h-[80vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-5 py-4 border-b border-rino-border">
              <h2 className="m-0 text-base font-semibold">Add repository</h2>
              <button
                type="button"
                className="text-rino-muted text-sm"
                onClick={() => setShowAdd(false)}
              >
                Close
              </button>
            </div>
            <div className="overflow-auto p-3 flex flex-col gap-1">
              {available.length === 0 ? (
                <p className="m-0 text-sm text-rino-muted p-3">
                  No repositories available to this installation.
                </p>
              ) : (
                available.map((repo) => (
                  <button
                    key={repo.github_repo_id}
                    type="button"
                    disabled={repo.connected || busy}
                    onClick={() => onConnect(repo)}
                    className="flex items-center justify-between gap-3 text-left px-3 py-3 rounded-xl hover:bg-[#FAFAF9] disabled:opacity-50"
                  >
                    <span className="font-mono text-sm font-medium">
                      {repo.full_name}
                    </span>
                    <span className="text-xs text-rino-muted">
                      {repo.connected ? "Connected" : "Add"}
                    </span>
                  </button>
                ))
              )}
            </div>
            <p className="m-0 px-5 py-3 text-xs text-rino-muted border-t border-rino-border">
              Signed in as {user.github_login}. Repos come from the GitHub App
              installation.
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
