export const apiBase = process.env.NEXT_PUBLIC_API_URL || "/api";

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase}${path}`);
  if (!res.ok) {
    throw new Error(`Erro ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}
