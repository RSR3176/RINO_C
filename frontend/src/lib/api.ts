export type Role = "admin" | "developer";

export type User = {
  id: string;
  github_login: string;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
  role: Role;
  org: { id: string; name: string; slug: string };
};

function publicApiBase(): string {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
    /\/$/,
    ""
  );
}

export function githubLoginUrl(roleHint: Role): string {
  const base = publicApiBase();
  return `${base}/auth/github/login?role_hint=${roleHint}`;
}

export async function fetchMe(cookieHeader?: string): Promise<User | null> {
  const base =
    typeof window === "undefined"
      ? (process.env.INTERNAL_API_URL || publicApiBase()).replace(/\/$/, "")
      : publicApiBase();

  const res = await fetch(`${base}/api/me`, {
    method: "GET",
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    credentials: "include",
    cache: "no-store",
  });

  if (res.status === 401 || res.status === 403) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to load session (${res.status})`);
  }
  return (await res.json()) as User;
}

export async function logout(): Promise<void> {
  const base = publicApiBase();
  await fetch(`${base}/auth/logout-public`, {
    method: "POST",
    credentials: "include",
  });
}
