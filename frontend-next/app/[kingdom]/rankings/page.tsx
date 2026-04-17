"use client";
import React, { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { fetchJson } from "@/components/api";
import { fmt } from "@/components/format";

const RANKING_TYPES = [
  { key: "power", label: "Power", icon: "⚡" },
  { key: "kill_points", label: "Kill Points", icon: "⚔️" },
  { key: "t4_kills", label: "T4 Kills", icon: "🗡️" },
  { key: "t5_kills", label: "T5 Kills", icon: "💎" },
  { key: "dead", label: "Dead Troops", icon: "💀" },
  { key: "rss_gathered", label: "RSS Gathered", icon: "🌾" },
  { key: "helps", label: "Helps", icon: "🤝" },
] as const;

interface RankingEntry {
  rank: number;
  governor_id: string;
  governor_name?: string | null;
  alliance_tag?: string | null;
  value?: number | null;
  power?: number | null;
  kill_points?: number | null;
}

interface RankingResponse {
  id: number;
  ranking_type: string;
  total_governors: number;
  source?: string | null;
  captured_at?: string | null;
  entries: RankingEntry[];
}

interface RankingHistoryEntry {
  id?: number;
  ranking_type: string;
  total_governors: number;
  source?: string | null;
  captured_at?: string | null;
}

function RankBadge({ rank }: { rank: number }) {
  if (rank === 1)
    return <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-amber-500/20 text-amber-300 font-bold text-sm border border-amber-500/40">1</span>;
  if (rank === 2)
    return <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-zinc-400/20 text-zinc-300 font-bold text-sm border border-zinc-400/40">2</span>;
  if (rank === 3)
    return <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-orange-600/20 text-orange-400 font-bold text-sm border border-orange-600/40">3</span>;
  return <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-zinc-800 text-zinc-400 font-medium text-xs">{rank}</span>;
}

export default function RankingsPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const [type, setType] = useState("power");

  const { data, error, isLoading } = useSWR<RankingResponse>(
    `/kingdoms/${kingdom}/rankings?type=${type}`,
    fetchJson,
    { refreshInterval: 10_000 }
  );

  const { data: historyData } = useSWR<RankingHistoryEntry[]>(
    `/kingdoms/${kingdom}/rankings/history`,
    fetchJson,
    { refreshInterval: 30_000 }
  );

  const ranking = data;
  const history = historyData ?? [];
  const entries = ranking?.entries ?? [];
  const activeType = RANKING_TYPES.find((t) => t.key === type);

  return (
    <main className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <span>🏆</span> Rankings
          </h1>
          <p className="text-muted text-sm mt-1 flex items-center gap-2">
            Captured via protocol interception · Kingdom {kingdom}
            <span className="inline-flex items-center gap-1 text-xs text-green-400">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              Live (10s)
            </span>
          </p>
        </div>
        {ranking?.captured_at && (
          <div className="text-xs text-zinc-500 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            Last capture: {new Date(ranking.captured_at).toLocaleString()}
          </div>
        )}
      </div>

      {/* Type selector tabs */}
      <div className="flex flex-wrap gap-2">
        {RANKING_TYPES.map((rt) => (
          <button
            key={rt.key}
            onClick={() => setType(rt.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
              type === rt.key
                ? "bg-accent/20 text-accent border border-accent/40"
                : "bg-zinc-800/40 text-zinc-400 border border-zinc-700/50 hover:border-zinc-600 hover:text-zinc-200"
            }`}
          >
            <span>{rt.icon}</span>
            {rt.label}
          </button>
        ))}
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="card flex items-center gap-3">
          <div className="animate-spin h-5 w-5 border-2 border-blue-400 border-t-transparent rounded-full" />
          <span className="text-muted">Carregando rankings…</span>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="card border-red-500/30 bg-red-500/5">
          <p className="text-red-400 text-sm">Falha a carregar rankings. O sistema pode ainda não ter dados capturados.</p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && entries.length === 0 && (
        <div className="card text-center py-12">
          <div className="text-4xl mb-3">📊</div>
          <h3 className="text-lg font-semibold">Sem dados de ranking</h3>
          <p className="text-muted text-sm mt-1">
            Rankings são capturados automaticamente via Frida quando abres a página de rankings no jogo.
          </p>
        </div>
      )}

      {/* Rankings table */}
      {entries.length > 0 && (
        <div className="card overflow-hidden p-0">
          <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between">
            <h2 className="font-semibold flex items-center gap-2">
              {activeType?.icon} {activeType?.label} Ranking
            </h2>
            <span className="text-xs text-zinc-500">{ranking?.total_governors ?? entries.length} governors</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted text-xs uppercase tracking-wider border-b border-border/30">
                  <th className="text-center px-3 py-2 w-12">#</th>
                  <th className="text-left px-3 py-2">Governor</th>
                  <th className="text-left px-3 py-2">Alliance</th>
                  <th className="text-right px-3 py-2">{activeType?.label ?? "Value"}</th>
                  <th className="text-right px-3 py-2">Power</th>
                  <th className="text-right px-3 py-2">Kill Points</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, i: number) => (
                  <tr
                    key={`${entry.rank}-${entry.governor_id}`}
                    className={`border-b border-border/10 hover:bg-zinc-800/40 transition-colors ${
                      i < 3 ? "bg-zinc-800/20" : ""
                    }`}
                  >
                    <td className="text-center px-3 py-2.5">
                      <RankBadge rank={entry.rank} />
                    </td>
                    <td className="px-3 py-2.5">
                      <Link
                        href={`/governors/${entry.governor_id}`}
                        className="font-medium hover:text-blue-400 transition-colors"
                      >
                        {entry.governor_name ?? `Gov #${entry.governor_id}`}
                      </Link>
                      <div className="text-xs text-zinc-500">ID: {entry.governor_id}</div>
                    </td>
                    <td className="px-3 py-2.5">
                      {entry.alliance_tag ? (
                        <span className="px-1.5 py-0.5 rounded bg-zinc-700/60 text-xs font-medium">
                          [{entry.alliance_tag}]
                        </span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="text-right px-3 py-2.5 font-semibold">{fmt(entry.value)}</td>
                    <td className="text-right px-3 py-2.5 text-muted">{fmt(entry.power)}</td>
                    <td className="text-right px-3 py-2.5 text-muted">{fmt(entry.kill_points)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Capture history */}
      {history.length > 0 && (
        <div className="card space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <span>📜</span> Capture History
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {history.slice(0, 12).map((snap, i: number) => {
              const capturedAtLabel = snap.captured_at ? new Date(snap.captured_at).toLocaleString() : "Unknown capture time";
              return (
                <div
                  key={snap.id ?? i}
                  className="flex items-center gap-3 p-3 rounded-lg bg-zinc-800/40 border border-zinc-700/30"
                >
                  <div className="w-9 h-9 rounded-lg bg-zinc-700/60 flex items-center justify-center text-xs font-mono text-zinc-400">
                    #{i + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {RANKING_TYPES.find((t) => t.key === snap.ranking_type)?.label ?? snap.ranking_type}
                    </div>
                    <div className="text-xs text-zinc-500">
                      {snap.total_governors} governors · {capturedAtLabel}
                    </div>
                  </div>
                  <div className="text-xs text-zinc-600">{snap.source}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </main>
  );
}
