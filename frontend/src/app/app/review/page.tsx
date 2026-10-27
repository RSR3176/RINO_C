import { Suspense } from "react";
import { AppShell } from "@/components/AppShell";
import { CodeReviewPanel } from "@/components/CodeReviewPanel";
import { requireUser } from "@/lib/session";

const NAV = [
  { href: "/app", label: "Repository Dashboard" },
  { href: "/app/review", label: "Code Review" },
  { href: "/app/testing", label: "Testing" },
  { href: "/app/performance", label: "Performance" },
];

export default async function ReviewPage() {
  const user = await requireUser(["developer", "admin"]);
  return (
    <AppShell user={user} nav={NAV}>
      <h1 className="m-0 text-[26px] font-bold tracking-tight">Code Review</h1>
      <p className="m-0 text-sm text-rino-muted">
        Root-cause · Confirm Issue · verify fix · Approve & Open Draft PR
        (rino/* only)
      </p>
      <Suspense fallback={<p className="text-sm text-rino-muted">Loading…</p>}>
        <CodeReviewPanel />
      </Suspense>
    </AppShell>
  );
}
