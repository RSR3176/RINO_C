import { AppShell } from "@/components/AppShell";
import { RepositorySetup } from "@/components/RepositorySetup";
import { requireUser } from "@/lib/session";

const NAV = [
  { href: "/admin", label: "Repository Setup" },
  { href: "/admin/settings", label: "Settings" },
];

export default async function AdminHomePage() {
  const user = await requireUser(["admin"]);

  return (
    <AppShell user={user} nav={NAV} sectionLabel="Admin">
      <RepositorySetup user={user} />
    </AppShell>
  );
}
