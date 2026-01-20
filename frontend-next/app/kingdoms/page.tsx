import { redirect } from "next/navigation";

export default async function KingdomRedirect({ searchParams }: { searchParams: Promise<{ k?: string }> }) {
  const { k } = await searchParams;
  if (k) {
    redirect(`/kingdoms/${k}`);
  }
  return null;
}
