import type { User } from "@/lib/api";

export type TestEnv = "github_actions" | "dev_instance" | "rino_sandbox";
export type RepoStatus =
  | "pending"
  | "ready"
  | "needs_attention"
  | "access_revoked";

export type GithubInstallation = {
  installed: boolean;
  installation_id: number | null;
  account_login: string | null;
  account_type: string | null;
  suspended: boolean;
  app_slug: string | null;
  configured: boolean;
};

export type RepoTestConfig = {
  test_env: TestEnv | null;
  workflow_file: string | null;
  setup_command: string | null;
  test_command: string | null;
  python_version: string | null;
  shared_dev_instance: boolean;
  last_checked_at: string | null;
  last_check_ok: boolean | null;
  last_check_detail: string | null;
  last_check_latency_ms: number | null;
};

export type Repository = {
  id: string;
  github_repo_id: string;
  github_full_name: string;
  default_branch: string;
  html_url: string | null;
  is_private: boolean;
  status: RepoStatus;
  status_detail: string | null;
  test_config: RepoTestConfig | null;
};

export type AvailableRepo = {
  github_repo_id: string;
  full_name: string;
  default_branch: string;
  html_url: string | null;
  private: boolean;
  connected: boolean;
};

export type WorkflowOption = { path: string; name: string };

function publicApiBase(): string {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
    /\/$/,
    ""
  );
}

async function api<T>(
  path: string,
  init?: RequestInit & { json?: unknown }
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${publicApiBase()}${path}`, {
    ...init,
    headers,
    credentials: "include",
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
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
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export function fetchInstallation() {
  return api<GithubInstallation>("/api/admin/github-app");
}

export function fetchInstallUrl() {
  return api<{ url: string; configured: boolean }>(
    "/api/admin/github-app/install-url"
  );
}

export function fetchRepos() {
  return api<Repository[]>("/api/admin/repos");
}

export function fetchAvailableRepos() {
  return api<AvailableRepo[]>("/api/admin/github/available-repos");
}

export function connectRepo(github_repo_id: string, full_name?: string) {
  return api<Repository>("/api/admin/repos", {
    method: "POST",
    json: { github_repo_id, full_name },
  });
}

export function saveTestConfig(
  repoId: string,
  body: Partial<RepoTestConfig> & { test_env?: TestEnv | null }
) {
  return api<Repository>(`/api/admin/repos/${repoId}/test-config`, {
    method: "PUT",
    json: body,
  });
}

export function testConnection(repoId: string) {
  return api<{
    ok: boolean;
    detail: string;
    latency_ms: number | null;
    repository: Repository;
  }>(`/api/admin/repos/${repoId}/test-connection`, { method: "POST" });
}

export function fetchWorkflows(repoId: string) {
  return api<WorkflowOption[]>(`/api/admin/repos/${repoId}/workflows`);
}

export type { User };
