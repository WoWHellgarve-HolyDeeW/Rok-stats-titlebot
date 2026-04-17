"use client";
import React, { use, useEffect, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetchJson } from "@/components/api";
import { fmt, fmtFull } from "@/components/format";
import PlayerAvatar from "@/components/PlayerAvatar";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";

/* ───── Shield countdown helper ───── */
function ShieldTimer({ expiresSec }: { expiresSec: number }) {
  const [left, setLeft] = useState(expiresSec);
  useEffect(() => {
    if (left <= 0) return;
    const t = setInterval(() => setLeft((p) => Math.max(0, p - 1)), 1000);
    return () => clearInterval(t);
  }, [left]);

  if (left <= 0) return <span className="text-red-400 font-semibold">Expired</span>;
  const h = Math.floor(left / 3600);
  const m = Math.floor((left % 3600) / 60);
  const s = left % 60;
  return (
    <span className="font-mono text-lg text-green-400">
      {String(h).padStart(2, "0")}:{String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
    </span>
  );
}

/* ───── Shield type badge color ───── */
function shieldBadge(type: string | null) {
  const colors: Record<string, string> = {
    "8h": "bg-blue-500/20 text-blue-300 border-blue-500/40",
    "24h": "bg-indigo-500/20 text-indigo-300 border-indigo-500/40",
    "3d": "bg-purple-500/20 text-purple-300 border-purple-500/40",
    peace: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  };
  const label = type ?? "unknown";
  return (
    <span className={`px-2 py-0.5 rounded text-xs border ${colors[label] ?? "bg-zinc-700 text-zinc-300 border-zinc-600"}`}>
      {label.toUpperCase()}
    </span>
  );
}

/* ───── Stat card ───── */
function StatCard({
  label,
  value,
  delta,
  icon,
}: {
  label: string;
  value: string;
  delta?: number | null;
  icon?: string;
}) {
  return (
    <div className="card relative overflow-hidden">
      {icon && <span className="absolute top-2 right-3 text-2xl opacity-10">{icon}</span>}
      <div className="text-muted text-xs uppercase tracking-wider">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
      {delta !== null && delta !== undefined && (
        <div className={`text-sm mt-0.5 ${delta >= 0 ? "text-green-400" : "text-red-400"}`}>
          {delta >= 0 ? "▲ +" : "▼ "}
          {fmt(delta)}
        </div>
      )}
    </div>
  );
}

/* ───── Chart colors ───── */
const CHART_COLORS = {
  power: "#3b82f6",
  kill_points: "#ef4444",
  dead: "#f59e0b",
  t4_kills: "#8b5cf6",
  t5_kills: "#ec4899",
  rss_gathered: "#10b981",
  helps: "#06b6d4",
};

/* ───── Custom tooltip for dark theme ───── */
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-zinc-400 mb-1">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
          <span className="text-zinc-300">{p.name}:</span>
          <span className="font-bold text-white">{fmtFull(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

/* ───── History Charts Component ───── */
const CHART_TABS = [
  { key: "power", label: "Power", color: CHART_COLORS.power },
  { key: "combat", label: "Combat", color: CHART_COLORS.kill_points },
  { key: "kills", label: "Kill Tiers", color: CHART_COLORS.t4_kills },
  { key: "economy", label: "Economy", color: CHART_COLORS.rss_gathered },
] as const;

function HistoryCharts({ history }: { history: any[] }) {
  const [tab, setTab] = useState<string>("power");

  // Prepare chart data (chronological)
  const chartData = [...history].reverse().map((s) => ({
    date: s.created_at?.split("T")[0] ?? s.created_at,
    power: s.power ?? 0,
    kill_points: s.kill_points ?? 0,
    dead: s.dead ?? 0,
    t1_kills: s.t1_kills ?? 0,
    t2_kills: s.t2_kills ?? 0,
    t3_kills: s.t3_kills ?? 0,
    t4_kills: s.t4_kills ?? 0,
    t5_kills: s.t5_kills ?? 0,
    victories: s.victories ?? 0,
    defeats: s.defeats ?? 0,
    rss_gathered: s.rss_gathered ?? 0,
    rss_assistance: s.rss_assistance ?? 0,
    helps: s.helps ?? 0,
    acclaims: s.acclaims ?? 0,
    healed: s.healed ?? 0,
  }));

  return (
    <section className="card space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-lg font-semibold">📈 Stat History</h2>
        <div className="flex gap-1 bg-zinc-800 rounded-lg p-1">
          {CHART_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 text-xs rounded-md transition-all ${
                tab === t.key
                  ? "bg-zinc-600 text-white font-medium"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          {tab === "power" ? (
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="gradPower" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART_COLORS.power} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={CHART_COLORS.power} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} />
              <YAxis stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
              <Tooltip content={<ChartTooltip />} />
              <Area type="monotone" dataKey="power" name="Power" stroke={CHART_COLORS.power} fill="url(#gradPower)" strokeWidth={2} dot={{ r: 3 }} />
            </AreaChart>
          ) : tab === "combat" ? (
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} />
              <YAxis stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              <Line type="monotone" dataKey="kill_points" name="Kill Points" stroke={CHART_COLORS.kill_points} strokeWidth={2} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="dead" name="Dead" stroke={CHART_COLORS.dead} strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          ) : tab === "kills" ? (
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} />
              <YAxis stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              <Line type="monotone" dataKey="t1_kills" name="T1 Kills" stroke="#71717a" strokeWidth={1} dot={false} />
              <Line type="monotone" dataKey="t2_kills" name="T2 Kills" stroke="#22c55e" strokeWidth={1} dot={false} />
              <Line type="monotone" dataKey="t3_kills" name="T3 Kills" stroke="#3b82f6" strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="t4_kills" name="T4 Kills" stroke={CHART_COLORS.t4_kills} strokeWidth={2} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="t5_kills" name="T5 Kills" stroke={CHART_COLORS.t5_kills} strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          ) : (
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} />
              <YAxis stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              <Line type="monotone" dataKey="rss_gathered" name="RSS Gathered" stroke={CHART_COLORS.rss_gathered} strokeWidth={2} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="helps" name="Helps" stroke={CHART_COLORS.helps} strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </section>
  );
}

export default function GovernorDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: govId } = use(params);
  const { data, error } = useSWR(() => `/governors/${govId}`, fetchJson, {
    refreshInterval: 30_000,
  });

  // Enhanced data from /complete endpoint
  const [complete, setComplete] = useState<any>(null);
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  useEffect(() => {
    if (!data) return;
    const gov = data as any;
    const kd = gov.kingdom;
    if (!kd) return;
    fetch(`${apiBase}/kingdoms/${kd}/governors/${govId}/complete`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setComplete)
      .catch(() => {});
  }, [data, apiBase, govId]);

  if (error) {
    return (
      <main className="container py-8">
        <div className="card border-red-500/30 bg-red-500/5">
          <h1 className="text-xl font-bold text-red-400">Erro</h1>
          <p className="text-muted mt-1">Governador não encontrado ou falha de conexão.</p>
          <Link href="/" className="inline-block mt-3 text-sm text-blue-400 hover:underline">
            ← Voltar
          </Link>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="container py-8">
        <div className="card flex items-center gap-3">
          <div className="animate-spin h-5 w-5 border-2 border-blue-400 border-t-transparent rounded-full" />
          <span className="text-muted">Carregando perfil…</span>
        </div>
      </main>
    );
  }

  const gov = data as any;
  const profile = gov.profile;
  const shield = profile?.shield;
  const linkedChars = profile?.linked_characters ?? [];
  const linkedAccounts = gov.linked_accounts ?? [];

  return (
    <main className="container py-8 space-y-6">
      {/* ───── Header ───── */}
      <header className="flex flex-col md:flex-row md:items-end gap-4 border-b border-border pb-4">
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <PlayerAvatar name={gov.name} avatarUrl={gov.avatar_url} size="lg" />
            <h1 className="text-2xl font-bold">{gov.name}</h1>
            {profile?.is_online && (
              <span className="flex items-center gap-1.5 text-xs text-green-400 bg-green-500/10 border border-green-500/30 px-2 py-0.5 rounded-full">
                <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                Online
              </span>
            )}
          </div>
          <p className="text-muted text-sm mt-1">
            ID: {gov.governor_id} ·{" "}
            <Link href={`/${gov.kingdom}/home`} className="text-blue-400 hover:underline">
              Kingdom {gov.kingdom}
            </Link>{" "}
            · Alliance: {gov.alliance ?? "N/A"}
            <Link
              href={`/compare?ids=${gov.governor_id}`}
              className="ml-3 text-xs text-purple-400 hover:underline"
            >
              ⚔️ Comparar
            </Link>
          </p>
        </div>

        {/* Shield Panel */}
        {shield && (
          <div
            className={`card flex items-center gap-4 px-4 py-3 border ${
              shield.active
                ? "border-green-500/40 bg-green-500/5"
                : "border-zinc-700 bg-zinc-800/50"
            }`}
          >
            <div className="text-2xl">{shield.active ? "🛡️" : "⚔️"}</div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted uppercase tracking-wider">Shield</span>
                {shield.type && shieldBadge(shield.type)}
              </div>
              {shield.active && shield.remaining_sec ? (
                <ShieldTimer expiresSec={shield.remaining_sec} />
              ) : (
                <span className="text-sm text-zinc-500">No active shield</span>
              )}
            </div>
          </div>
        )}
      </header>

      {/* ───── Profile info bar ───── */}
      {profile && (
        <section className="flex flex-wrap gap-4 text-sm">
          {profile.vip_level != null && (
            <div className="flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-300 px-3 py-1 rounded-full">
              <span className="font-bold">VIP {profile.vip_level}</span>
            </div>
          )}
          {profile.city_hall_level != null && (
            <div className="flex items-center gap-1.5 bg-blue-500/10 border border-blue-500/30 text-blue-300 px-3 py-1 rounded-full">
              CH Lv. {profile.city_hall_level}
            </div>
          )}
          {profile.civilization && (
            <div className="flex items-center gap-1.5 bg-teal-500/10 border border-teal-500/30 text-teal-300 px-3 py-1 rounded-full">
              🏛️ {profile.civilization}
            </div>
          )}
          {profile.commander_count != null && (
            <div className="flex items-center gap-1.5 bg-purple-500/10 border border-purple-500/30 text-purple-300 px-3 py-1 rounded-full">
              {profile.commander_count} Commanders
            </div>
          )}
          {profile.highest_power != null && (
            <div className="flex items-center gap-1.5 bg-rose-500/10 border border-rose-500/30 text-rose-300 px-3 py-1 rounded-full">
              Peak: {fmt(profile.highest_power)}
            </div>
          )}
          {profile.kvk_contribution != null && profile.kvk_contribution > 0 && (
            <div className="flex items-center gap-1.5 bg-orange-500/10 border border-orange-500/30 text-orange-300 px-3 py-1 rounded-full">
              KvK: {fmt(profile.kvk_contribution)}
            </div>
          )}
          {profile.source && (
            <div className="text-xs text-zinc-500 self-center ml-auto">
              Source: {profile.source} · Updated: {profile.updated_at ?? "—"}
            </div>
          )}
        </section>
      )}

      {/* ───── Main stat cards ───── */}
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard label="Power" value={fmt(gov.latest?.power)} delta={gov.deltas?.power} icon="⚡" />
        <StatCard label="Kill Points" value={fmt(gov.latest?.kill_points)} delta={gov.deltas?.kill_points} icon="⚔️" />
        <StatCard label="Dead" value={fmt(gov.latest?.dead)} delta={gov.deltas?.dead} icon="💀" />
        <StatCard label="Victories" value={fmt(gov.latest?.victories)} delta={gov.deltas?.victories} icon="🏆" />
        <StatCard label="Defeats" value={fmt(gov.latest?.defeats)} delta={gov.deltas?.defeats} icon="🏳️" />
      </section>

      {/* ───── Kill Tier Breakdown ───── */}
      {(gov.latest?.t1_kills || gov.latest?.t4_kills || gov.latest?.t5_kills) && (
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Kills */}
          <div className="card space-y-3">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <span>⚔️</span> Kill Breakdown
            </h2>
            <div className="space-y-2">
              {[
                { tier: "T1", val: gov.latest?.t1_kills, delta: gov.deltas?.t1_kills, color: "bg-zinc-500" },
                { tier: "T2", val: gov.latest?.t2_kills, delta: gov.deltas?.t2_kills, color: "bg-green-500" },
                { tier: "T3", val: gov.latest?.t3_kills, delta: gov.deltas?.t3_kills, color: "bg-blue-500" },
                { tier: "T4", val: gov.latest?.t4_kills, delta: gov.deltas?.t4_kills, color: "bg-purple-500" },
                { tier: "T5", val: gov.latest?.t5_kills, delta: gov.deltas?.t5_kills, color: "bg-red-500" },
              ].map((t) => {
                const total = (gov.latest?.t1_kills ?? 0) + (gov.latest?.t2_kills ?? 0) + (gov.latest?.t3_kills ?? 0) + (gov.latest?.t4_kills ?? 0) + (gov.latest?.t5_kills ?? 0);
                const pct = total > 0 ? ((t.val ?? 0) / total) * 100 : 0;
                return (
                  <div key={t.tier} className="flex items-center gap-3">
                    <span className="text-xs font-bold w-6 text-zinc-400">{t.tier}</span>
                    <div className="flex-1 h-6 bg-zinc-800 rounded-full overflow-hidden relative">
                      <div className={`h-full ${t.color} rounded-full transition-all`} style={{ width: `${Math.max(pct, 1)}%` }} />
                      <span className="absolute inset-0 flex items-center justify-center text-xs font-medium text-white/90">
                        {fmt(t.val)}
                      </span>
                    </div>
                    {t.delta != null && t.delta !== 0 && (
                      <span className={`text-xs w-16 text-right ${t.delta > 0 ? "text-green-400" : "text-red-400"}`}>
                        {t.delta > 0 ? "+" : ""}{fmt(t.delta)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Deaths */}
          <div className="card space-y-3">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <span>💀</span> Death Breakdown
            </h2>
            <div className="space-y-2">
              {[
                { tier: "T1", val: gov.latest?.t1_deaths, delta: gov.deltas?.t1_deaths, color: "bg-zinc-500" },
                { tier: "T2", val: gov.latest?.t2_deaths, delta: gov.deltas?.t2_deaths, color: "bg-green-500" },
                { tier: "T3", val: gov.latest?.t3_deaths, delta: gov.deltas?.t3_deaths, color: "bg-blue-500" },
                { tier: "T4", val: gov.latest?.t4_deaths, delta: gov.deltas?.t4_deaths, color: "bg-purple-500" },
                { tier: "T5", val: gov.latest?.t5_deaths, delta: gov.deltas?.t5_deaths, color: "bg-red-500" },
              ].map((t) => {
                const total = (gov.latest?.t1_deaths ?? 0) + (gov.latest?.t2_deaths ?? 0) + (gov.latest?.t3_deaths ?? 0) + (gov.latest?.t4_deaths ?? 0) + (gov.latest?.t5_deaths ?? 0);
                const pct = total > 0 ? ((t.val ?? 0) / total) * 100 : 0;
                return (
                  <div key={t.tier} className="flex items-center gap-3">
                    <span className="text-xs font-bold w-6 text-zinc-400">{t.tier}</span>
                    <div className="flex-1 h-6 bg-zinc-800 rounded-full overflow-hidden relative">
                      <div className={`h-full ${t.color} rounded-full transition-all`} style={{ width: `${Math.max(pct, 1)}%` }} />
                      <span className="absolute inset-0 flex items-center justify-center text-xs font-medium text-white/90">
                        {fmt(t.val)}
                      </span>
                    </div>
                    {t.delta != null && t.delta !== 0 && (
                      <span className={`text-xs w-16 text-right ${t.delta > 0 ? "text-green-400" : "text-red-400"}`}>
                        {t.delta > 0 ? "+" : ""}{fmt(t.delta)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* ───── Economy & Battle Stats ───── */}
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard label="RSS Gathered" value={fmt(gov.latest?.rss_gathered)} icon="🌾" />
        <StatCard label="RSS Assistance" value={fmt(gov.latest?.rss_assistance)} icon="🤝" />
        <StatCard label="Helps" value={fmt(gov.latest?.helps)} delta={gov.deltas?.helps} icon="🔨" />
        <StatCard label="Acclaims" value={fmt(gov.latest?.acclaims)} delta={gov.deltas?.acclaims} icon="🏅" />
        <StatCard label="Highest Acclaims" value={fmt(gov.latest?.highest_acclaims)} icon="👑" />
        <StatCard label="Healed" value={fmt(gov.latest?.healed)} delta={gov.deltas?.healed} icon="🏥" />
        <StatCard label="Scout Times" value={fmt(gov.latest?.scout_times)} icon="🔭" />
        {gov.latest?.kvk_contribution != null && gov.latest.kvk_contribution > 0 && (
          <StatCard label="KvK Contribution" value={fmt(gov.latest?.kvk_contribution)} icon="🗡️" />
        )}
        {gov.latest?.civilization && (
          <StatCard label="Civilization" value={gov.latest.civilization} icon="🏛️" />
        )}
      </section>

      {/* ───── Linked Characters ───── */}
      {(linkedChars.length > 0 || linkedAccounts.length > 0) && (
        <section className="card space-y-3">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <span>🔗</span> Linked Characters
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {linkedChars.map((lc: any, i: number) => (
              <div
                key={`c-${i}`}
                className="flex items-center gap-3 p-3 rounded-lg bg-zinc-800/60 border border-zinc-700/50 hover:border-blue-500/40 transition-colors"
              >
                <div className="w-9 h-9 rounded-full bg-blue-500/20 border border-blue-500/40 flex items-center justify-center text-sm font-bold text-blue-300">
                  {(lc.governor_name ?? "?")[0]}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{lc.governor_name ?? `Gov ${lc.governor_id}`}</div>
                  <div className="text-xs text-muted">
                    ID: {lc.governor_id ?? "—"}
                    {lc.power != null && <> · Power: {fmt(lc.power)}</>}
                    {lc.kingdom != null && <> · KD {lc.kingdom}</>}
                  </div>
                </div>
              </div>
            ))}
            {linkedAccounts.map((la: any, i: number) => (
              <Link
                key={`a-${i}`}
                href={`/governors/${la.governor_id}`}
                className="flex items-center gap-3 p-3 rounded-lg bg-zinc-800/60 border border-zinc-700/50 hover:border-purple-500/40 transition-colors"
              >
                <div className="w-9 h-9 rounded-full bg-purple-500/20 border border-purple-500/40 flex items-center justify-center text-sm font-bold text-purple-300">
                  {la.is_main ? "M" : "L"}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">
                    {la.governor_name ?? `Gov ${la.governor_id}`}
                    {la.is_main && <span className="ml-1 text-xs text-amber-400">(Main)</span>}
                  </div>
                  <div className="text-xs text-muted">
                    ID: {la.governor_id}
                    {la.verified && <span className="ml-1 text-green-400">✓ Verified</span>}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* ───── History Charts ───── */}
      {gov.history && gov.history.length > 1 && (
        <HistoryCharts history={gov.history} />
      )}

      {/* ───── Enhanced Data from /complete endpoint ───── */}
      {complete && (
        <>
          {/* Metadata bar */}
          <section className="flex flex-wrap gap-3 text-sm">
            {complete.ocr?.total_scans != null && (
              <div className="flex items-center gap-1.5 bg-zinc-700/30 border border-zinc-600/40 text-zinc-300 px-3 py-1 rounded-full">
                📊 {complete.ocr.total_scans} scans
              </div>
            )}
            {complete.ocr?.first_seen && (
              <div className="flex items-center gap-1.5 bg-zinc-700/30 border border-zinc-600/40 text-zinc-300 px-3 py-1 rounded-full">
                📅 First: {complete.ocr.first_seen.split("T")[0].split(" ")[0]}
              </div>
            )}
            {complete.ocr?.last_seen && (
              <div className="flex items-center gap-1.5 bg-zinc-700/30 border border-zinc-600/40 text-zinc-300 px-3 py-1 rounded-full">
                🕐 Last: {complete.ocr.last_seen.split("T")[0].split(" ")[0]}
              </div>
            )}
            {complete.chat_messages > 0 && (
              <div className="flex items-center gap-1.5 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 px-3 py-1 rounded-full">
                💬 {complete.chat_messages} chat messages
              </div>
            )}
          </section>

          {/* Location card */}
          {complete.location && (
            <section className="card space-y-2">
              <h2 className="text-lg font-semibold flex items-center gap-2">📍 Last Known Location</h2>
              <div className="flex items-center gap-6 text-sm">
                <div className="font-mono text-xl text-green-400">
                  ({complete.location.x}, {complete.location.y})
                </div>
                {complete.location.shield_type && (
                  <div className="flex items-center gap-1.5">
                    🛡️ {shieldBadge(complete.location.shield_type)}
                    {complete.location.shield_expires_at && (
                      <span className="text-zinc-500 text-xs">
                        expires {complete.location.shield_expires_at.split("T")[0]}
                      </span>
                    )}
                  </div>
                )}
                <span className="text-zinc-500 text-xs ml-auto">
                  Updated: {complete.location.updated_at?.split("T")[0] ?? "—"}
                </span>
              </div>
            </section>
          )}

          {/* Rankings */}
          {complete.rankings && complete.rankings.length > 0 && (
            <section className="card space-y-3">
              <h2 className="text-lg font-semibold flex items-center gap-2">🏅 Ranking Appearances</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm table">
                  <thead>
                    <tr className="text-muted text-xs">
                      <th className="text-left">Type</th>
                      <th className="text-right">Rank</th>
                      <th className="text-right">Value</th>
                      <th className="text-right">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {complete.rankings.map((r: any, i: number) => (
                      <tr key={i} className="hover:bg-[#0d1626] border-t border-zinc-800">
                        <td className="capitalize">{r.ranking_type?.replace(/_/g, " ") ?? "—"}</td>
                        <td className="text-right font-bold">
                          <span className={r.rank <= 3 ? "text-amber-400" : r.rank <= 10 ? "text-blue-400" : ""}>
                            #{r.rank}
                          </span>
                        </td>
                        <td className="text-right">{fmt(r.value)}</td>
                        <td className="text-right text-zinc-500">{r.captured_at?.split("T")[0] ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Name change history */}
          {complete.name_changes && complete.name_changes.length > 0 && (
            <section className="card space-y-3">
              <h2 className="text-lg font-semibold flex items-center gap-2">✏️ Name History</h2>
              <div className="space-y-1">
                {complete.name_changes.map((nc: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 text-sm py-1 border-b border-zinc-800 last:border-0">
                    <span className="text-zinc-500 text-xs w-24">{nc.changed_at?.split("T")[0] ?? "—"}</span>
                    <span className="text-red-400 line-through">{nc.old_name}</span>
                    <span className="text-zinc-500">→</span>
                    <span className="text-green-400">{nc.new_name}</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {/* ───── Último Snapshot ───── */}
      <section className="card space-y-3">
        <h2 className="text-lg font-semibold">Último Snapshot</h2>
        {gov.latest ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted">T1 Kills:</span> {fmt(gov.latest.t1_kills)}
            </div>
            <div>
              <span className="text-muted">T2 Kills:</span> {fmt(gov.latest.t2_kills)}
            </div>
            <div>
              <span className="text-muted">T3 Kills:</span> {fmt(gov.latest.t3_kills)}
            </div>
            <div>
              <span className="text-muted">T4 Kills:</span> {fmt(gov.latest.t4_kills)}
            </div>
            <div>
              <span className="text-muted">T5 Kills:</span> {fmt(gov.latest.t5_kills)}
            </div>
            <div>
              <span className="text-muted">Victories:</span> {fmt(gov.latest.victories)}
            </div>
            <div>
              <span className="text-muted">Defeats:</span> {fmt(gov.latest.defeats)}
            </div>
            <div>
              <span className="text-muted">Healed:</span> {fmt(gov.latest.healed)}
            </div>
            <div>
              <span className="text-muted">Scout Times:</span> {fmt(gov.latest.scout_times)}
            </div>
            <div>
              <span className="text-muted">RSS Gathered:</span> {fmt(gov.latest.rss_gathered)}
            </div>
            <div>
              <span className="text-muted">RSS Assistance:</span> {fmt(gov.latest.rss_assistance)}
            </div>
            <div>
              <span className="text-muted">Helps:</span> {fmt(gov.latest.helps)}
            </div>
            <div>
              <span className="text-muted">Acclaims:</span> {fmt(gov.latest.acclaims)}
            </div>
            <div>
              <span className="text-muted">Highest Acclaims:</span> {fmt(gov.latest.highest_acclaims)}
            </div>
            {gov.latest.kvk_contribution != null && gov.latest.kvk_contribution > 0 && (
              <div>
                <span className="text-muted">KvK Contribution:</span> {fmt(gov.latest.kvk_contribution)}
              </div>
            )}
            {gov.latest.civilization && (
              <div>
                <span className="text-muted">Civilization:</span> {gov.latest.civilization}
              </div>
            )}
            <div>
              <span className="text-muted">Scan:</span> {gov.latest.created_at}
            </div>
          </div>
        ) : (
          <p className="text-muted">Sem dados de snapshot.</p>
        )}
      </section>

      {/* ───── History table ───── */}
      <section className="card space-y-3">
        <h2 className="text-lg font-semibold">Histórico ({gov.history?.length ?? 0} snapshots)</h2>
        {gov.history && gov.history.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm table">
              <thead>
                <tr className="text-muted">
                  <th className="text-left">Data</th>
                  <th className="text-right">Power</th>
                  <th className="text-right">KP</th>
                  <th className="text-right">Dead</th>
                  <th className="text-right">T1</th>
                  <th className="text-right">T2</th>
                  <th className="text-right">T3</th>
                  <th className="text-right">T4</th>
                  <th className="text-right">T5</th>
                  <th className="text-right">Vic</th>
                  <th className="text-right">Def</th>
                  <th className="text-right">Accl</th>
                </tr>
              </thead>
              <tbody>
                {gov.history.map((s: any, i: number) => (
                  <tr key={i} className="hover:bg-[#0d1626]">
                    <td>{s.created_at}</td>
                    <td className="text-right">{fmt(s.power)}</td>
                    <td className="text-right">{fmt(s.kill_points)}</td>
                    <td className="text-right">{fmt(s.dead)}</td>
                    <td className="text-right">{fmt(s.t1_kills)}</td>
                    <td className="text-right">{fmt(s.t2_kills)}</td>
                    <td className="text-right">{fmt(s.t3_kills)}</td>
                    <td className="text-right">{fmt(s.t4_kills)}</td>
                    <td className="text-right">{fmt(s.t5_kills)}</td>
                    <td className="text-right">{fmt(s.victories)}</td>
                    <td className="text-right">{fmt(s.defeats)}</td>
                    <td className="text-right">{fmt(s.acclaims)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-muted">Sem histórico disponível.</p>
        )}
      </section>
    </main>
  );
}
