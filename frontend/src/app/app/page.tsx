import { AppShell } from "@/components/AppShell";
import { RepositoryDashboard } from "@/components/RepositoryDashboard";
import { requireUser } from "@/lib/session";

const NAV = [
  { href: "/app", label: "Repository Dashboard" },
  { href: "/app/review", label: "Code Review" },
  { href: "/app/testing", label: "Testing" },
  { href: "/app/performance", label: "Performance" },
];

export default async function DeveloperHomePage() {
  const user = await requireUser(["developer", "admin"]);

  return (
    <AppShell user={user} nav={NAV}>
      <h1 className="m-0 text-[26px] font-bold tracking-tight">
        Repository Dashboard
      </h1>
      <RepositoryDashboard />
    </AppShell>
  );
}
