import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { BrandMark } from "@/components/BrandMark";
import { fetchMe, githubLoginUrl } from "@/lib/api";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const me = await fetchMe(cookieHeader || undefined);
  if (me) {
    redirect(me.role === "admin" ? "/admin" : "/app");
  }

  const params = await searchParams;
  const error = params.error;

  return (
    <div className="min-h-screen flex flex-col bg-rino-bg">
      <main className="flex-grow flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-[420px] flex flex-col gap-7">
          <div className="flex flex-col items-center gap-3.5 text-center">
            <BrandMark />
            <h1 className="m-0 text-[34px] font-bold tracking-[-0.03em] text-rino-ink">
              Rino
            </h1>
            <p className="m-0 text-rino-muted leading-relaxed max-w-[340px]">
              Runs your repo&apos;s own tests and checks, triages what breaks,
              and suggests fixes you approve.
            </p>
          </div>

          <div className="bg-white border border-rino-border rounded-[20px] p-5 flex flex-col gap-3 shadow-card">
            <a
              href={githubLoginUrl("developer")}
              className="role-btn role-pri group flex items-center gap-3.5 w-full box-border px-4 py-3.5 rounded-[14px] border border-rino-indigo bg-rino-indigo text-white text-left no-underline hover:bg-rino-indigoDark hover:text-white"
            >
              <span className="w-[34px] h-[34px] rounded-[10px] flex-none flex items-center justify-center bg-white/15 text-white">
                <CodeIcon />
              </span>
              <span className="min-w-0">
                <span className="block font-semibold">
                  Login with GitHub as Developer
                </span>
                <span className="block text-[13px] opacity-90">
                  Run analysis, review findings and fixes
                </span>
              </span>
              <span className="ml-auto text-lg" aria-hidden>
                ›
              </span>
            </a>

            <a
              href={githubLoginUrl("admin")}
              className="flex items-center gap-3.5 w-full box-border px-4 py-3.5 rounded-[14px] border border-rino-border bg-white text-rino-ink text-left no-underline hover:border-rino-indigo hover:bg-[#FAFAFF] hover:text-rino-ink"
            >
              <span className="w-[34px] h-[34px] rounded-[10px] flex-none flex items-center justify-center bg-rino-indigoSoft text-rino-indigo">
                <ShieldIcon />
              </span>
              <span className="min-w-0">
                <span className="block font-semibold">
                  Login with GitHub as Admin
                </span>
                <span className="block text-[13px] text-rino-muted">
                  Set up repos, people and triage rules
                </span>
              </span>
              <span className="ml-auto text-lg text-rino-muted" aria-hidden>
                ›
              </span>
            </a>
          </div>

          <p className="m-0 text-center text-[13px] text-rino-muted">
            Access is granted by your Admin.
          </p>

          {error ? (
            <p className="m-0 text-center text-[13px] text-red-700 bg-red-50 border border-red-100 rounded-xl px-3 py-2">
              GitHub login failed. Please try again.
            </p>
          ) : null}
        </div>
      </main>
    </div>
  );
}

function CodeIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M16 18l6-6-6-6" />
      <path d="M8 6l-6 6 6 6" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z" />
    </svg>
  );
}
