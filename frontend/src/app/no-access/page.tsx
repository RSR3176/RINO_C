import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";

export default function NoAccessPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-rino-bg px-4">
      <div className="w-full max-w-[420px] flex flex-col items-center gap-6 text-center">
        <BrandMark />
        <h1 className="m-0 text-[28px] font-bold tracking-tight">Rino</h1>
        <div className="bg-white border border-rino-border rounded-[20px] p-6 shadow-card w-full">
          <p className="m-0 text-[17px] font-semibold text-rino-ink">
            Ask your Admin for access
          </p>
          <p className="mt-2 mb-0 text-[14px] text-rino-muted leading-relaxed">
            Your GitHub account is not on this Rino org yet. Contact an Admin so
            they can grant you Developer or Admin access.
          </p>
        </div>
        <Link
          href="/"
          className="text-[14px] font-medium text-rino-indigo hover:text-[#312E81]"
        >
          ← Back to login
        </Link>
      </div>
    </div>
  );
}
