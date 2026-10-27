"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@/lib/api";
import { logout } from "@/lib/api";

type NavItem = { href: string; label: string };

export function AppShell({
  user,
  nav,
  sectionLabel,
  children,
}: {
  user: User;
  nav: NavItem[];
  sectionLabel?: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();

  async function onLogout() {
    await logout();
    router.push("/");
    router.refresh();
  }

  return (
    <div className="min-h-screen flex flex-col bg-rino-bg">
      <div className="flex flex-wrap items-stretch flex-1 bg-rino-bg">
        <nav
          className="flex-1 basis-[220px] bg-white border-r border-rino-border px-3.5 py-[22px] flex flex-col gap-0.5 box-border"
          aria-label="Main"
        >
          <div className="flex items-center gap-2.5 text-lg font-bold tracking-tight px-2.5 pb-[18px]">
            <span
              aria-hidden
              className="inline-block w-[22px] h-[22px] rounded-[7px]"
              style={{
                background: "#4338CA",
                boxShadow: "inset -7px -7px 0 #818CF8",
              }}
            />
            Rino
          </div>
          {sectionLabel ? (
            <div className="text-[11px] font-semibold text-[#78716C] tracking-[0.08em] uppercase px-2.5 pt-3 pb-1.5">
              {sectionLabel}
            </div>
          ) : null}
          {nav.map((item) => {
            const on = pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={on ? "page" : undefined}
                className={`flex items-center gap-2.5 p-2.5 rounded-[9px] font-medium no-underline ${
                  on
                    ? "bg-rino-indigoSoft text-rino-indigo font-semibold"
                    : "text-[#44403C] hover:bg-[#F5F5F4] hover:text-rino-ink"
                }`}
              >
                <span
                  className={`w-4 h-4 rounded-[5px] border-[1.75px] border-current box-border flex-none opacity-80 ${
                    on ? "bg-current opacity-100" : ""
                  }`}
                />
                {item.label}
              </Link>
            );
          })}
          <div className="flex-grow" />
          <button
            type="button"
            onClick={onLogout}
            className="flex items-center gap-2.5 p-2.5 rounded-[9px] text-[#44403C] font-medium text-left hover:bg-[#F5F5F4] hover:text-rino-ink"
          >
            <span className="w-4 h-4 rounded-[5px] border-[1.75px] border-current box-border flex-none opacity-80" />
            Log out
          </button>
        </nav>

        <div className="flex-[999_1_640px] min-w-0 flex flex-col">
          <header className="flex flex-wrap gap-2.5 items-center px-8 py-3 bg-white border-b border-rino-border">
            <span className="text-[13px] text-rino-muted flex-grow">
              {user.org.name}
            </span>
            <span className="text-[13px] text-rino-muted">{user.github_login}</span>
            <span className="text-[11px] font-semibold rounded-full px-2.5 py-1 bg-rino-indigoSoft text-rino-indigo capitalize">
              {user.role}
            </span>
            {user.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={user.avatar_url}
                alt=""
                className="w-8 h-8 rounded-full border-2 border-white shadow-[0_0_0_1px_#E7E5E4]"
              />
            ) : (
              <span className="w-8 h-8 rounded-full bg-[#C7D2FE] border-2 border-white shadow-[0_0_0_1px_#E7E5E4]" />
            )}
          </header>
          <main className="px-9 pt-8 pb-14 flex flex-col gap-6 max-w-[1240px] w-full box-border">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
