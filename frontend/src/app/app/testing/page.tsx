import { Suspense } from "react";
import { AppShell } from "@/components/AppShell";
import { TestingDashboard } from "@/components/TestingDashboard";
import { requireUser } from "@/lib/session";

const NAV = [
  { href: "/app", label: "Repository Dashboard" },
  { href: "/app/review", label: "Code Review" },
  { href: "/app/testing", label: "Testing" },
  { href: "/app/performance", label: "Performance" },
];

export default async function TestingPage() {
  const user = await requireUser(["developer", "admin"]);
  return (
    <AppShell user={user} nav={NAV}>
      <h1 className="m-0 text-[26px] font-bold tracking-tight">
        Testing Dashboard
      </h1>
      <p className="m-0 text-sm text-rino-muted">
        Existing tests only · before vs after a verified fix · regressions in
        red
      </p>
      <Suspense fallback={<p className="text-sm text-rino-muted">Loading…</p>}>
        <TestingDashboard />
      </Suspense>
    </AppShell>
  );
}
