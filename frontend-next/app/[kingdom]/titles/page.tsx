import { redirect } from "next/navigation";

export default async function TitlesRedirectPage({
  params,
}: {
  params: Promise<{ kingdom: string }>;
}) {
  const { kingdom } = await params;
  redirect(`/${kingdom}/scanner?tab=titles`);
}
