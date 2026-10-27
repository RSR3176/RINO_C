import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchMe, type Role, type User } from "@/lib/api";

export async function requireUser(allowed?: Role[]): Promise<User> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const me = await fetchMe(cookieHeader || undefined);
  if (!me) {
    redirect("/");
  }
  if (allowed && !allowed.includes(me.role)) {
    redirect(me.role === "admin" ? "/admin" : "/app");
  }
  return me;
}
