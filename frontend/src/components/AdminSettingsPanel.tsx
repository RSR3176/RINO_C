"use client";

import { useCallback, useEffect, useState } from "react";

type Member = {
  user_id: string;
  github_login: string;
  name: string | null;
  role: "admin" | "developer";
  is_you: boolean;
  last_active: string | null;
  invite_pending: boolean;
};

type Triage = {
  setup_failed_enabled: boolean;
  missing_package_enabled: boolean;
  flaky_enabled: boolean;
  flaky_rerun_count: number;
  ignored_paths: string[];
  core_modules: string[];
  fix_limits: { max_attempts: number; max_files_changed: number };
};

type AuditRow = {
  id: string;
  created_at: string;
  actor_login: string | null;
  action: string;
  detail: string | null;
};

type Tab = "users" | "audit";

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
  if (res.status === 204) return undefined as T;
  return res.json();
}

function fmtWhen(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "Just now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)} min ago`;
  return d.toLocaleString();
}

export function AdminSettingsPanel() {
  const [tab, setTab] = useState<Tab>("users");
  const [members, setMembers] = useState<Member[]>([]);
  const [triage, setTriage] = useState<Triage | null>(null);
  const [draft, setDraft] = useState<Triage | null>(null);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [inviteLogin, setInviteLogin] = useState("");
  const [inviteRole, setInviteRole] = useState<"developer" | "admin">(
    "developer"
  );
  const [newModule, setNewModule] = useState("");
  const [newIgnored, setNewIgnored] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const dirty =
    draft && triage ? JSON.stringify(draft) !== JSON.stringify(triage) : false;

  const load = useCallback(async () => {
    const [m, t, a] = await Promise.all([
      api<Member[]>("/api/admin/settings/members"),
      api<Triage>("/api/admin/settings/triage"),
      api<AuditRow[]>("/api/admin/settings/audit?limit=100"),
    ]);
    setMembers(m);
    setTriage(t);
    setDraft(t);
    setAudit(a);
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api<Triage>("/api/admin/settings/triage", {
        method: "PUT",
        body: JSON.stringify(draft),
      });
      setTriage(saved);
      setDraft(saved);
      setMsg("Settings saved.");
      const a = await api<AuditRow[]>("/api/admin/settings/audit?limit=100");
      setAudit(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function invite() {
    setBusy(true);
    setError(null);
    try {
      await api("/api/admin/settings/members/invite", {
        method: "POST",
        body: JSON.stringify({
          github_login: inviteLogin,
          role: inviteRole,
        }),
      });
      setInviteLogin("");
      setMsg(`Invited ${inviteLogin}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invite failed");
    } finally {
      setBusy(false);
    }
  }

  async function setRole(userId: string, role: "admin" | "developer") {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/admin/settings/members/${userId}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Role change failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {error ? (
        <p className="m-0 text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
          {error}
        </p>
      ) : null}
      {msg ? (
        <p className="m-0 text-sm text-[#15803D] bg-[#F0FDF4] border border-[#BBF7D0] rounded-xl px-3 py-2">
          {msg}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3 items-center justify-between">
        <div className="flex gap-2">
          {(
            [
              ["users", "Users & rules"],
              ["audit", "Audit log"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              className={`min-h-9 px-3.5 rounded-full text-sm font-medium border ${
                tab === k
                  ? "bg-rino-indigoSoft text-rino-indigo border-transparent"
                  : "bg-white text-rino-muted border-[#D6D3D1]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "users" ? (
          <div className="flex gap-2 items-center">
            {dirty ? (
              <span className="text-xs font-semibold text-[#C2410C]">
                Unsaved changes
              </span>
            ) : null}
            <button
              type="button"
              disabled={!dirty || busy}
              onClick={() => setDraft(triage)}
              className="min-h-9 px-3.5 rounded-[10px] border border-[#D6D3D1] bg-white text-sm font-semibold disabled:opacity-50"
            >
              Discard
            </button>
            <button
              type="button"
              disabled={!dirty || busy}
              onClick={save}
              className="min-h-9 px-3.5 rounded-[10px] border border-rino-indigo bg-rino-indigo text-white text-sm font-semibold disabled:opacity-50"
            >
              Save changes
            </button>
          </div>
        ) : null}
      </div>

      {tab === "audit" ? (
        <section className="bg-white border border-rino-border rounded-2xl shadow-card overflow-hidden">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-rino-muted bg-[#FAFAF9]">
                <th className="px-4 py-3 font-semibold">When</th>
                <th className="px-4 py-3 font-semibold">Actor</th>
                <th className="px-4 py-3 font-semibold">Action</th>
                <th className="px-4 py-3 font-semibold">Detail</th>
              </tr>
            </thead>
            <tbody>
              {audit.length === 0 ? (
                <tr>
                  <td
                    colSpan={4}
                    className="px-4 py-8 text-center text-rino-muted"
                  >
                    No audit events yet.
                  </td>
                </tr>
              ) : (
                audit.map((row) => (
                  <tr
                    key={row.id}
                    className="border-t border-[#F0EFED] hover:bg-[#FAFAF9]"
                  >
                    <td className="px-4 py-3 text-xs text-rino-muted whitespace-nowrap">
                      {fmtWhen(row.created_at)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {row.actor_login || "—"}
                    </td>
                    <td className="px-4 py-3 font-semibold text-xs">
                      {row.action}
                    </td>
                    <td className="px-4 py-3 text-xs break-all">
                      {row.detail || "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </section>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="bg-white border border-rino-border rounded-2xl p-5 shadow-card flex flex-col gap-4">
            <div className="flex flex-wrap gap-2 items-center justify-between">
              <h2 className="m-0 text-[15px] font-semibold">Users & roles</h2>
              <div className="flex flex-wrap gap-2 items-center">
                <input
                  className="min-h-9 border border-[#D6D3D1] rounded-[10px] px-3 text-sm"
                  placeholder="GitHub username"
                  value={inviteLogin}
                  onChange={(e) => setInviteLogin(e.target.value)}
                />
                <select
                  className="min-h-9 border border-[#D6D3D1] rounded-[10px] px-2 text-sm"
                  value={inviteRole}
                  onChange={(e) =>
                    setInviteRole(e.target.value as "admin" | "developer")
                  }
                >
                  <option value="developer">Developer</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  type="button"
                  disabled={busy || !inviteLogin.trim()}
                  onClick={invite}
                  className="min-h-9 px-3 rounded-[10px] border border-rino-indigo bg-rino-indigo text-white text-sm font-semibold disabled:opacity-50"
                >
                  Invite user
                </button>
              </div>
            </div>
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-rino-muted border-b border-rino-border">
                  <th className="py-2 font-semibold">GitHub username</th>
                  <th className="py-2 font-semibold">Role</th>
                  <th className="py-2 font-semibold">Last active</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.user_id} className="border-b border-[#F0EFED]">
                    <td className="py-3">
                      <span className="font-mono text-xs">{m.github_login}</span>
                      {m.is_you ? (
                        <span className="ml-2 text-xs text-rino-muted">
                          (you)
                        </span>
                      ) : null}
                      {m.invite_pending ? (
                        <span className="ml-2 text-xs text-[#C2410C]">
                          Invite pending
                        </span>
                      ) : null}
                    </td>
                    <td className="py-3">
                      <select
                        className="min-h-8 border border-[#D6D3D1] rounded-lg px-2 text-sm"
                        value={m.role}
                        disabled={busy || m.is_you}
                        onChange={(e) =>
                          setRole(
                            m.user_id,
                            e.target.value as "admin" | "developer"
                          )
                        }
                      >
                        <option value="admin">Admin</option>
                        <option value="developer">Developer</option>
                      </select>
                    </td>
                    <td className="py-3 text-xs text-rino-muted">
                      {fmtWhen(m.last_active)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="bg-white border border-rino-border rounded-2xl p-5 shadow-card flex flex-col gap-4">
            <h2 className="m-0 text-[15px] font-semibold">Triage rules</h2>
            <p className="m-0 text-xs text-rino-muted">
              Backed by <span className="font-mono">rules.yaml</span>. Not a
              code bug toggles:
            </p>
            {draft ? (
              <div className="flex flex-col gap-2 text-sm">
                {(
                  [
                    ["setup_failed_enabled", "Setup failed (install / build)"],
                    [
                      "missing_package_enabled",
                      "Missing package (ImportError for a dependency)",
                    ],
                    ["flaky_enabled", "Flaky — passes when re-run"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="flex gap-2 items-center">
                    <input
                      type="checkbox"
                      checked={Boolean(draft[key])}
                      onChange={(e) =>
                        setDraft({ ...draft, [key]: e.target.checked })
                      }
                    />
                    {label}
                  </label>
                ))}
                <label className="flex gap-2 items-center text-xs text-rino-muted">
                  Flaky re-run count
                  <input
                    type="number"
                    min={1}
                    max={10}
                    className="w-16 min-h-8 border border-[#D6D3D1] rounded-lg px-2"
                    value={draft.flaky_rerun_count}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        flaky_rerun_count: Number(e.target.value) || 2,
                      })
                    }
                  />
                </label>
              </div>
            ) : null}

            <div className="flex flex-col gap-2">
              <h3 className="m-0 text-sm font-semibold">Ignored paths</h3>
              <ul className="m-0 p-0 list-none flex flex-col gap-1">
                {(draft?.ignored_paths || []).map((p) => (
                  <li
                    key={p}
                    className="flex justify-between items-center font-mono text-xs bg-[#FAFAF9] rounded-lg px-3 py-2"
                  >
                    {p}
                    <button
                      type="button"
                      className="text-[#B91C1C] font-sans font-semibold"
                      onClick={() =>
                        draft &&
                        setDraft({
                          ...draft,
                          ignored_paths: draft.ignored_paths.filter(
                            (x) => x !== p
                          ),
                        })
                      }
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                <input
                  className="flex-1 min-h-9 border border-[#D6D3D1] rounded-[10px] px-3 text-sm font-mono"
                  placeholder="vendor/"
                  value={newIgnored}
                  onChange={(e) => setNewIgnored(e.target.value)}
                />
                <button
                  type="button"
                  className="min-h-9 px-3 rounded-[10px] border border-[#D6D3D1] text-sm font-semibold"
                  onClick={() => {
                    if (!draft || !newIgnored.trim()) return;
                    setDraft({
                      ...draft,
                      ignored_paths: [
                        ...draft.ignored_paths,
                        newIgnored.trim(),
                      ],
                    });
                    setNewIgnored("");
                  }}
                >
                  Add
                </button>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <h3 className="m-0 text-sm font-semibold">Core modules</h3>
              <p className="m-0 text-xs text-rino-muted">
                A failing test in these paths is always Critical.
              </p>
              <ul className="m-0 p-0 list-none flex flex-col gap-1">
                {(draft?.core_modules || []).map((p) => (
                  <li
                    key={p}
                    className="flex justify-between items-center font-mono text-xs bg-[#FAFAF9] rounded-lg px-3 py-2"
                  >
                    {p}
                    <button
                      type="button"
                      className="text-[#B91C1C] font-sans font-semibold"
                      onClick={() =>
                        draft &&
                        setDraft({
                          ...draft,
                          core_modules: draft.core_modules.filter(
                            (x) => x !== p
                          ),
                        })
                      }
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                <input
                  className="flex-1 min-h-9 border border-[#D6D3D1] rounded-[10px] px-3 text-sm font-mono"
                  placeholder="src/payments/"
                  value={newModule}
                  onChange={(e) => setNewModule(e.target.value)}
                />
                <button
                  type="button"
                  className="min-h-9 px-3 rounded-[10px] border border-[#D6D3D1] text-sm font-semibold"
                  onClick={() => {
                    if (!draft || !newModule.trim()) return;
                    setDraft({
                      ...draft,
                      core_modules: [
                        ...draft.core_modules,
                        newModule.trim(),
                      ],
                    });
                    setNewModule("");
                  }}
                >
                  Add
                </button>
              </div>
            </div>

            <div className="flex flex-col gap-2 border-t border-[#F0EFED] pt-4">
              <h3 className="m-0 text-sm font-semibold">Fix limits</h3>
              <p className="m-0 text-xs text-rino-muted">
                Test files are always read-only. Fixes that skip or remove tests
                are rejected.
              </p>
              {draft ? (
                <div className="flex flex-wrap gap-4 text-sm">
                  <label className="flex flex-col gap-1">
                    Max attempts
                    <input
                      type="number"
                      min={1}
                      max={10}
                      className="w-24 min-h-9 border border-[#D6D3D1] rounded-[10px] px-3"
                      value={draft.fix_limits.max_attempts}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          fix_limits: {
                            ...draft.fix_limits,
                            max_attempts: Number(e.target.value) || 3,
                          },
                        })
                      }
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    Max files changed
                    <input
                      type="number"
                      min={1}
                      max={10}
                      className="w-24 min-h-9 border border-[#D6D3D1] rounded-[10px] px-3"
                      value={draft.fix_limits.max_files_changed}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          fix_limits: {
                            ...draft.fix_limits,
                            max_files_changed: Number(e.target.value) || 3,
                          },
                        })
                      }
                    />
                  </label>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
