import { Suspense } from "react";
import { AppShell } from "@/components/AppShell";
import { PerformanceDashboard } from "@/components/PerformanceDashboard";
import { requireUser } from "@/lib/session";

const NAV = [
  { href: "/app", label: "Repository Dashboard" },
  { href: "/app/review", label: "Code Review" },
  { href: "/app/testing", label: "Testing" },
  { href: "/app/performance", label: "Performance" },
];

export default async function PerformancePage() {
  const user = await requireUser(["developer", "admin"]);
  return (
    <AppShell user={user} nav={NAV}>
      <h1 className="m-0 text-[26px] font-bold tracking-tight">
        Agent Performance
      </h1>
      <p className="m-0 text-sm text-rino-muted">
        From bug found to PR opened — and what it cost.
      </p>
      <Suspense fallback={<p className="text-sm text-rino-muted">Loading…</p>}>
        <PerformanceDashboard />
      </Suspense>
    </AppShell>
  );
}
