"use client";
import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { apiBase } from "@/components/api";
import { fmt, fmtFull } from "@/components/format";

/* ───── Types ───── */
interface GovernorComparison {
  governor_id: number;
  name: string;
  alliance: string | null;
  kingdom: number | null;
  latest: Record<string, any> | null;
  deltas: Record<string, number> | null;
  history: Record<string, any>[];
  profile: Record<string, any> | null;
}

/* ───── Stat row definition ───── */
const STAT_ROWS = [
  { key: "power", label: "Power", icon: "⚡", format: "number" },
  { key: "kill_points", label: "Kill Points", icon: "⚔️", format: "number" },
  { key: "dead", label: "Dead", icon: "💀", format: "number" },
  { key: "t1_kills", label: "T1 Kills", icon: "", format: "number" },
  { key: "t2_kills", label: "T2 Kills", icon: "", format: "number" },
  { key: "t3_kills", label: "T3 Kills", icon: "", format: "number" },
  { key: "t4_kills", label: "T4 Kills", icon: "", format: "number" },
  { key: "t5_kills", label: "T5 Kills", icon: "", format: "number" },
  { key: "t1_deaths", label: "T1 Deaths", icon: "", format: "number" },
  { key: "t2_deaths", label: "T2 Deaths", icon: "", format: "number" },
  { key: "t3_deaths", label: "T3 Deaths", icon: "", format: "number" },
  { key: "t4_deaths", label: "T4 Deaths", icon: "", format: "number" },
  { key: "t5_deaths", label: "T5 Deaths", icon: "", format: "number" },
  { key: "victories", label: "Victories", icon: "🏆", format: "number" },
  { key: "defeats", label: "Defeats", icon: "🏳️", format: "number" },
  { key: "healed", label: "Healed", icon: "🏥", format: "number" },
  { key: "scout_times", label: "Scout Times", icon: "🔭", format: "number" },
  { key: "rss_gathered", label: "RSS Gathered", icon: "🌾", format: "number" },
  { key: "rss_assistance", label: "RSS Assistance", icon: "🤝", format: "number" },
  { key: "helps", label: "Helps", icon: "🔨", format: "number" },
  { key: "acclaims", label: "Acclaims", icon: "🏅", format: "number" },
  { key: "highest_acclaims", label: "Highest Acclaims", icon: "👑", format: "number" },
  { key: "kvk_contribution", label: "KvK Contribution", icon: "🗡️", format: "number" },
] as const;

const PROFILE_ROWS = [
  { key: "vip_level", label: "VIP Level", icon: "⭐" },
  { key: "city_hall_level", label: "City Hall", icon: "🏰" },
  { key: "highest_power", label: "Highest Power", icon: "📈" },
  { key: "civilization", label: "Civilization", icon: "🏛️" },
] as const;

/* ───── Helper: find best value ───── */
function getBestIdx(govs: GovernorComparison[], key: string): number {
  let bestIdx = -1;
  let bestVal = -Infinity;
  govs.forEach((g, i) => {
    const v = g.latest?.[key];
    if (v != null && typeof v === "number" && v > bestVal) {
      bestVal = v;
      bestIdx = i;
    }
  });
  return bestIdx;
}

/* ───── Main Page ───── */
export default function ComparePage() {
  const [inputIds, setInputIds] = useState("");
  const [governors, setGovernors] = useState<GovernorComparison[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Read IDs from URL parameters on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const ids = params.get("ids");
    if (ids) {
      setInputIds(ids);
      doCompare(ids);
    }
  }, []);

  const doCompare = useCallback(async (idsStr?: string) => {
    const ids = (idsStr ?? inputIds).split(",").map((s) => s.trim()).filter(Boolean);
    if (ids.length < 2) {
      setError("Insere pelo menos 2 IDs de governor (separados por vírgula)");
      return;
    }
    if (ids.length > 6) {
      setError("Máximo 6 governors para comparar");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/compare/governors?ids=${ids.join(",")}`);
      if (!res.ok) throw new Error(`Error ${res.status}`);
      const data = await res.json();
      setGovernors(data.governors ?? []);
      // Update URL
      const url = new URL(window.location.href);
      url.searchParams.set("ids", ids.join(","));
      window.history.replaceState({}, "", url.toString());
    } catch (e: any) {
      setError(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [inputIds]);

  const colColors = [
    "text-blue-400",
    "text-purple-400",
    "text-green-400",
    "text-amber-400",
    "text-rose-400",
    "text-cyan-400",
  ];

  return (
    <main className="container py-8 space-y-6">
      <header className="border-b border-border pb-4">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-blue-400 hover:underline text-sm">← Voltar</Link>
          <h1 className="text-2xl font-bold">⚔️ Comparador de Governors</h1>
        </div>
        <p className="text-muted text-sm mt-1">
          Compara até 6 governors lado a lado com todos os stats
        </p>
      </header>

      {/* ───── Search bar ───── */}
      <section className="card flex flex-col md:flex-row gap-3">
        <input
          type="text"
          value={inputIds}
          onChange={(e) => setInputIds(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doCompare()}
          placeholder="Governor IDs (ex: 12345678, 23456789, 34567890)"
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500"
        />
        <button
          onClick={() => doCompare()}
          disabled={loading}
          className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
        >
          {loading ? "Carregando..." : "Comparar"}
        </button>
      </section>

      {error && (
        <div className="card border-red-500/30 bg-red-500/5 text-red-400 text-sm">{error}</div>
      )}

      {/* ───── Comparison Table ───── */}
      {governors.length >= 2 && (
        <section className="card overflow-x-auto">
          <table className="w-full text-sm">
            {/* Header: Governor names */}
            <thead>
              <tr className="border-b border-zinc-700">
                <th className="text-left py-3 px-3 text-muted text-xs uppercase tracking-wider w-48">Stat</th>
                {governors.map((g, i) => (
                  <th key={g.governor_id} className={`text-center py-3 px-3 ${colColors[i % colColors.length]}`}>
                    <Link href={`/governors/${g.governor_id}`} className="hover:underline font-bold text-base">
                      {g.name}
                    </Link>
                    <div className="text-xs text-zinc-500 font-normal mt-0.5">
                      {g.alliance ? `[${g.alliance}]` : ""} KD{g.kingdom ?? "?"}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {/* Profile rows */}
              {PROFILE_ROWS.map((row) => {
                // Only show if at least one governor has this value
                const hasData = governors.some(
                  (g) => g.profile?.[row.key] != null
                );
                if (!hasData) return null;
                return (
                  <tr key={row.key} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-2 px-3 text-muted text-xs">
                      {row.icon} {row.label}
                    </td>
                    {governors.map((g) => (
                      <td key={g.governor_id} className="text-center py-2 px-3 font-medium">
                        {g.profile?.[row.key] != null
                          ? typeof g.profile[row.key] === "number"
                            ? fmt(g.profile[row.key])
                            : g.profile[row.key]
                          : <span className="text-zinc-600">—</span>
                        }
                      </td>
                    ))}
                  </tr>
                );
              })}

              {/* Divider */}
              <tr>
                <td colSpan={governors.length + 1} className="py-1">
                  <div className="border-t border-zinc-700" />
                </td>
              </tr>

              {/* Stat rows */}
              {STAT_ROWS.map((row) => {
                const bestIdx = getBestIdx(governors, row.key);
                // Only show if at least one governor has this value
                const hasData = governors.some(
                  (g) => g.latest?.[row.key] != null && g.latest[row.key] !== 0
                );
                if (!hasData) return null;

                return (
                  <tr key={row.key} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-2 px-3 text-muted text-xs">
                      {row.icon} {row.label}
                    </td>
                    {governors.map((g, i) => {
                      const val = g.latest?.[row.key];
                      const delta = g.deltas?.[row.key];
                      const isBest = i === bestIdx && bestIdx >= 0;
                      return (
                        <td
                          key={g.governor_id}
                          className={`text-center py-2 px-3 ${
                            isBest ? "font-bold text-green-400" : "font-medium"
                          }`}
                        >
                          <div>{val != null ? fmtFull(val) : <span className="text-zinc-600">—</span>}</div>
                          {delta != null && delta !== 0 && (
                            <div className={`text-xs ${delta > 0 ? "text-green-500/70" : "text-red-500/70"}`}>
                              {delta > 0 ? "+" : ""}{fmt(delta)}
                            </div>
                          )}
                          {isBest && <span className="text-xs text-green-500/60">★</span>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {/* ───── Usage hint ───── */}
      {governors.length === 0 && !loading && !error && (
        <section className="card text-center py-12">
          <div className="text-4xl mb-4">⚔️</div>
          <h2 className="text-lg font-semibold text-zinc-300">Comparador de Governors</h2>
          <p className="text-muted mt-2 max-w-md mx-auto">
            Insere os IDs de 2-6 governors separados por vírgula para ver uma comparação detalhada
            de todos os stats lado a lado. O melhor valor em cada stat é destacado.
          </p>
          <p className="text-muted text-xs mt-4">
            Dica: Podes partilhar o link com ?ids=123,456,789 para dar a comparação a alguém.
          </p>
        </section>
      )}
    </main>
  );
}
