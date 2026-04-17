"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { fmt } from "@/components/format";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";

const COLORS = ["#6366f1", "#8b5cf6", "#a855f7", "#d946ef", "#ec4899"];
const KD_COLORS = { good: "#10b981", bad: "#ef4444", neutral: "#f59e0b" };

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-zinc-400 mb-1">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color ?? p.fill }} />
          <span className="text-zinc-300">{p.name}:</span>
          <span className="font-bold text-white">{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

interface CombatData {
  totals: Record<string, number>;
  top_killers: any[];
  top_dead: any[];
  best_kd_ratio: any[];
  worst_kd_ratio: any[];
}

type Tab = "killers" | "dead" | "best_kd" | "worst_kd";

export default function AnalyticsPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const [data, setData] = useState<CombatData | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("killers");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/analytics/combat`);
      if (!res.ok) throw new Error("Failed");
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, kdNum]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin h-8 w-8 border-2 border-blue-400 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">💀 Combat Analytics</h1>
        <div className="card text-muted">No combat data available.</div>
      </div>
    );
  }

  const t = data.totals;

  // Kill tier distribution for pie chart
  const tierData = [
    { name: "T1 Kills", value: t.total_t1 },
    { name: "T2 Kills", value: t.total_t2 },
    { name: "T3 Kills", value: t.total_t3 },
    { name: "T4 Kills", value: t.total_t4 },
    { name: "T5 Kills", value: t.total_t5 },
  ].filter((d) => d.value > 0);

  const tabItems: { key: Tab; label: string; icon: string }[] = [
    { key: "killers", label: "Top Killers", icon: "⚔️" },
    { key: "dead", label: "Top Dead", icon: "💀" },
    { key: "best_kd", label: "Best K/D", icon: "🏆" },
    { key: "worst_kd", label: "Worst K/D", icon: "📉" },
  ];

  const currentList =
    tab === "killers" ? data.top_killers :
    tab === "dead" ? data.top_dead :
    tab === "best_kd" ? data.best_kd_ratio :
    data.worst_kd_ratio;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">💀 Combat Analytics</h1>
        <p className="text-muted">{t.governor_count} governors tracked</p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
        <div className="card">
          <div className="text-xs text-muted uppercase">Total KP</div>
          <div className="text-lg font-bold text-blue-400">{fmt(t.total_kp)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">T1 Kills</div>
          <div className="text-lg font-bold">{fmt(t.total_t1)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">T2 Kills</div>
          <div className="text-lg font-bold">{fmt(t.total_t2)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">T3 Kills</div>
          <div className="text-lg font-bold">{fmt(t.total_t3)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">T4 Kills</div>
          <div className="text-lg font-bold text-purple-400">{fmt(t.total_t4)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">T5 Kills</div>
          <div className="text-lg font-bold text-pink-400">{fmt(t.total_t5)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Total Dead</div>
          <div className="text-lg font-bold text-red-400">{fmt(t.total_dead)}</div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Kill Tier Distribution */}
        <div className="card space-y-3">
          <h2 className="font-semibold">🎯 Kill Tier Distribution</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={tierData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={100}
                  dataKey="value"
                  label={({ name, percent }: any) => `${(name ?? "").replace(" Kills", "")} ${(percent * 100).toFixed(0)}%`}
                >
                  {tierData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip content={<ChartTooltip />} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Top 10 Killers Bar */}
        <div className="card space-y-3">
          <h2 className="font-semibold">⚔️ Top 10 by Total Kills</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={data.top_killers.slice(0, 10).map((g) => ({
                  name: g.name.length > 12 ? g.name.slice(0, 12) + "…" : g.name,
                  "Total Kills": g.total_kills,
                }))}
                layout="vertical"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis type="number" stroke="#71717a" tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(v)} />
                <YAxis type="category" dataKey="name" stroke="#71717a" tick={{ fontSize: 10 }} width={90} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="Total Kills" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Leaderboard Tabs */}
      <div className="card space-y-4">
        <div className="flex gap-1 bg-zinc-800 rounded-lg p-1 w-fit">
          {tabItems.map((ti) => (
            <button
              key={ti.key}
              onClick={() => setTab(ti.key)}
              className={`px-4 py-2 text-sm rounded-md transition-all ${
                tab === ti.key
                  ? "bg-zinc-600 text-white font-medium"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {ti.icon} {ti.label}
            </button>
          ))}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm table">
            <thead>
              <tr className="text-muted text-xs">
                <th className="text-left w-8">#</th>
                <th className="text-left">Governor</th>
                <th className="text-left">Alliance</th>
                <th className="text-right">Power</th>
                <th className="text-right">Kill Points</th>
                <th className="text-right">T4 Kills</th>
                <th className="text-right">T5 Kills</th>
                <th className="text-right">Total Kills</th>
                <th className="text-right">Dead</th>
                <th className="text-right">K/D Ratio</th>
              </tr>
            </thead>
            <tbody>
              {currentList.map((g: any, i: number) => (
                <tr key={g.governor_id} className="hover:bg-[#0d1626] border-t border-zinc-800">
                  <td className="text-muted">
                    {i < 3 ? ["🥇", "🥈", "🥉"][i] : i + 1}
                  </td>
                  <td>
                    <Link href={`/governors/${g.governor_id}`} className="text-blue-400 hover:underline">
                      {g.name}
                    </Link>
                  </td>
                  <td className="text-muted">{g.alliance ?? "—"}</td>
                  <td className="text-right">{fmt(g.power)}</td>
                  <td className="text-right">{fmt(g.kill_points)}</td>
                  <td className="text-right">{fmt(g.t4_kills)}</td>
                  <td className="text-right">{fmt(g.t5_kills)}</td>
                  <td className="text-right font-medium">{fmt(g.total_kills)}</td>
                  <td className="text-right text-red-400">{fmt(g.dead)}</td>
                  <td className="text-right">
                    <span
                      className={
                        g.kd_ratio >= 5
                          ? "text-green-400"
                          : g.kd_ratio >= 1
                          ? "text-yellow-400"
                          : "text-red-400"
                      }
                    >
                      {g.kd_ratio.toFixed(2)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
