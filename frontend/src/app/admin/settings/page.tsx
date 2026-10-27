import { AppShell } from "@/components/AppShell";
import { AdminSettingsPanel } from "@/components/AdminSettingsPanel";
import { requireUser } from "@/lib/session";

const NAV = [
  { href: "/admin", label: "Repository Setup" },
  { href: "/admin/settings", label: "Settings" },
];

export default async function AdminSettingsPage() {
  const user = await requireUser(["admin"]);

  return (
    <AppShell user={user} nav={NAV} sectionLabel="Admin">
      <div>
        <h1 className="m-0 text-[26px] font-bold tracking-tight">Settings</h1>
        <p className="mt-2 mb-0 text-sm text-rino-muted">
          People, triage rules and fix limits. Every change is logged.
        </p>
      </div>
      <AdminSettingsPanel />
    </AppShell>
  );
}
