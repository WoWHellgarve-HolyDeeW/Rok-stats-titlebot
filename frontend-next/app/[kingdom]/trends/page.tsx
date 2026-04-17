"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { fmt } from "@/components/format";
import { fmtDate } from "@/components/format";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-zinc-400 mb-1">{fmtDate(label, true)}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color ?? p.stroke }} />
          <span className="text-zinc-300">{p.name}:</span>
          <span className="font-bold text-white">{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

interface TrendPoint {
  date: string | null;
  scan_id: number;
  scan_type: string;
  source_file: string;
  session_id: string | null;
  batch_count: number;
  session_started_at: string | null;
  session_ended_at: string | null;
  governor_count: number;
  total_power: number;
  total_kp: number;
  total_dead: number;
  total_t4: number;
  total_t5: number;
  avg_power: number;
}

function trendLabel(value: string | null, includeTime = false) {
  return fmtDate(value, includeTime);
}

const TAB_ITEMS = [
  { key: "power", label: "Power", color: "#3b82f6" },
  { key: "combat", label: "Combat", color: "#ef4444" },
  { key: "kills", label: "Kill Tiers", color: "#8b5cf6" },
  { key: "overview", label: "Overview", color: "#10b981" },
] as const;

export default function TrendsPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<string>("power");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/trends`);
      if (!res.ok) throw new Error("Failed");
      const data = await res.json();
      setTrends(data.trends || []);
    } catch {
      setTrends([]);
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

  if (trends.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">📈 Kingdom Trends</h1>
        <div className="card text-muted">
          <p>No trend data available. Upload multiple scans to see kingdom stats over time.</p>
        </div>
      </div>
    );
  }

  const latest = trends[trends.length - 1];
  const prev = trends.length > 1 ? trends[trends.length - 2] : null;
  const delta = (curr: number, pr: number | undefined) =>
    pr !== undefined ? curr - pr : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">📈 Kingdom Trends</h1>
        <p className="text-muted">{trends.length} grouped scans tracked over time</p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-xs text-muted uppercase">Total Power</div>
          <div className="text-xl font-bold text-blue-400">{fmt(latest.total_power)}</div>
          {delta(latest.total_power, prev?.total_power) !== null && (
            <div className={`text-sm ${delta(latest.total_power, prev?.total_power)! >= 0 ? "text-green-400" : "text-red-400"}`}>
              {delta(latest.total_power, prev?.total_power)! >= 0 ? "+" : ""}{fmt(delta(latest.total_power, prev?.total_power)!)}
            </div>
          )}
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Total KP</div>
          <div className="text-xl font-bold text-red-400">{fmt(latest.total_kp)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Avg Power</div>
          <div className="text-xl font-bold text-green-400">{fmt(latest.avg_power)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Governors</div>
          <div className="text-xl font-bold">{latest.governor_count}</div>
        </div>
      </div>

      {/* Tab Selector */}
      <div className="flex gap-1 bg-zinc-800 rounded-lg p-1 w-fit">
        {TAB_ITEMS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm rounded-md transition-all ${
              tab === t.key
                ? "bg-zinc-600 text-white font-medium"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Charts */}
      <div className="card">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            {tab === "power" ? (
              <AreaChart data={trends}>
                <defs>
                  <linearGradient id="gradTotalPower" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(value) => trendLabel(value, trends.length <= 8)} />
                <YAxis stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
                <Tooltip content={<ChartTooltip />} />
                <Legend />
                <Area type="monotone" dataKey="total_power" name="Total Power" stroke="#3b82f6" fill="url(#gradTotalPower)" strokeWidth={2} dot={{ r: 3 }} />
                <Area type="monotone" dataKey="avg_power" name="Avg Power" stroke="#10b981" fill="none" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 2 }} />
              </AreaChart>
            ) : tab === "combat" ? (
              <LineChart data={trends}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(value) => trendLabel(value, trends.length <= 8)} />
                <YAxis stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
                <Tooltip content={<ChartTooltip />} />
                <Legend />
                <Line type="monotone" dataKey="total_kp" name="Total KP" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="total_dead" name="Total Dead" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            ) : tab === "kills" ? (
              <BarChart data={trends}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(value) => trendLabel(value, trends.length <= 8)} />
                <YAxis stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
                <Tooltip content={<ChartTooltip />} />
                <Legend />
                <Bar dataKey="total_t4" name="T4 Kills" fill="#8b5cf6" />
                <Bar dataKey="total_t5" name="T5 Kills" fill="#ec4899" />
              </BarChart>
            ) : (
              <LineChart data={trends}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(value) => trendLabel(value, trends.length <= 8)} />
                <YAxis stroke="#71717a" tick={{ fontSize: 11 }} />
                <Tooltip content={<ChartTooltip />} />
                <Legend />
                <Line type="monotone" dataKey="governor_count" name="Governor Count" stroke="#06b6d4" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>

      {/* Scan History Table */}
      <div className="card space-y-3">
        <h2 className="font-semibold">📋 Scan History</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm table">
            <thead>
              <tr className="text-muted text-xs">
                <th className="text-left">Date</th>
                <th className="text-right">Batches</th>
                <th className="text-right">Governors</th>
                <th className="text-right">Total Power</th>
                <th className="text-right">Total KP</th>
                <th className="text-right">Total Dead</th>
                <th className="text-right">T4 Kills</th>
                <th className="text-right">T5 Kills</th>
                <th className="text-right">Avg Power</th>
              </tr>
            </thead>
            <tbody>
              {[...trends].reverse().map((t, i) => (
                <tr key={t.scan_id} className="hover:bg-[#0d1626] border-t border-zinc-800">
                  <td>{trendLabel(t.session_ended_at || t.date, true)}</td>
                  <td className="text-right">{t.batch_count}</td>
                  <td className="text-right">{t.governor_count}</td>
                  <td className="text-right">{fmt(t.total_power)}</td>
                  <td className="text-right">{fmt(t.total_kp)}</td>
                  <td className="text-right">{fmt(t.total_dead)}</td>
                  <td className="text-right">{fmt(t.total_t4)}</td>
                  <td className="text-right">{fmt(t.total_t5)}</td>
                  <td className="text-right">{fmt(t.avg_power)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
