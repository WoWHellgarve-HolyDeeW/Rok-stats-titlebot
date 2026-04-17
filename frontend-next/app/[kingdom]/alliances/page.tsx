"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { fmt } from "@/components/format";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
} from "recharts";

const COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-zinc-400 mb-1">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
          <span className="text-zinc-300">{p.name}:</span>
          <span className="font-bold text-white">{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

interface Alliance {
  alliance: string;
  member_count: number;
  total_power: number;
  total_kills: number;
  avg_power: number;
}

interface CompareData {
  alliance: string;
  members: number;
  total_power: number;
  total_kp: number;
  total_dead: number;
  total_t4: number;
  total_t5: number;
  avg_power: number;
  avg_kp?: number;
  top_governor?: { governor_id: number; name: string; power: number } | null;
}

export default function AlliancesPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const [loading, setLoading] = useState(true);
  const [alliances, setAlliances] = useState<Alliance[]>([]);
  const [sortBy, setSortBy] = useState("total_power");
  const [sortDir, setSortDir] = useState("desc");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comparing, setComparing] = useState(false);
  const [compareData, setCompareData] = useState<CompareData[]>([]);

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  useEffect(() => {
    const fetchAlliances = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${apiBase}/kingdoms/${kdNum}/alliances`);
        if (res.ok) setAlliances(await res.json());
      } catch (err) {
        console.error("Failed to fetch alliances:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchAlliances();
  }, [apiBase, kdNum]);

  const toggleSelect = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else if (next.size < 6) next.add(name);
      return next;
    });
  };

  const handleCompare = useCallback(async () => {
    if (selected.size < 2) return;
    setComparing(true);
    try {
      const tags = Array.from(selected).join(",");
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/alliances/compare?tags=${encodeURIComponent(tags)}`);
      if (res.ok) {
        const data = await res.json();
        setCompareData(data.alliances || []);
      }
    } catch {
      console.error("Compare failed");
    } finally {
      setComparing(false);
    }
  }, [selected, apiBase, kdNum]);

  const sortedAlliances = [...alliances].sort((a, b) => {
    const aVal = a[sortBy as keyof Alliance];
    const bVal = b[sortBy as keyof Alliance];
    if (typeof aVal === "number" && typeof bVal === "number") {
      return sortDir === "asc" ? aVal - bVal : bVal - aVal;
    }
    return 0;
  });

  const handleSort = (field: string) => {
    if (sortBy === field) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortBy(field); setSortDir("desc"); }
  };

  const SortIcon = ({ field }: { field: string }) => (
    <span className="ml-1 opacity-50">
      {sortBy === field ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </span>
  );

  // Prepare comparison charts
  const barData = compareData.length >= 2
    ? ["total_power", "total_kp", "total_dead", "total_t4", "total_t5"].map((key) => {
        const labels: Record<string, string> = {
          total_power: "Power", total_kp: "Kill Points", total_dead: "Dead",
          total_t4: "T4 Kills", total_t5: "T5 Kills",
        };
        const row: Record<string, any> = { stat: labels[key] };
        compareData.forEach((a) => { row[a.alliance] = (a as any)[key] ?? 0; });
        return row;
      })
    : [];

  const radarKeys = ["total_power", "total_kp", "total_dead", "total_t4", "total_t5"];
  const maxVals: Record<string, number> = {};
  radarKeys.forEach((k) => {
    maxVals[k] = Math.max(1, ...compareData.map((a) => (a as any)[k] ?? 0));
  });
  const radarData = radarKeys.map((k) => {
    const labels: Record<string, string> = {
      total_power: "Power", total_kp: "KP", total_dead: "Dead",
      total_t4: "T4", total_t5: "T5",
    };
    const row: Record<string, any> = { stat: labels[k] };
    compareData.forEach((a) => {
      row[a.alliance] = Math.round(((a as any)[k] ?? 0) / maxVals[k] * 100);
    });
    return row;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">Alliance Management</h1>
          <p className="text-muted">View and compare alliance statistics</p>
        </div>
        {selected.size >= 2 && (
          <button onClick={handleCompare} disabled={comparing} className="btn">
            {comparing ? "Comparing…" : `⚖️ Compare ${selected.size} Alliances`}
          </button>
        )}
      </div>

      {/* Comparison Panel */}
      {compareData.length >= 2 && (
        <div className="space-y-6">
          {/* Side by Side Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {compareData.map((a, i) => (
              <div key={a.alliance} className="card space-y-2" style={{ borderLeft: `3px solid ${COLORS[i % COLORS.length]}` }}>
                <h3 className="font-semibold text-lg" style={{ color: COLORS[i % COLORS.length] }}>
                  {a.alliance}
                </h3>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><span className="text-muted">Members:</span> {a.members}</div>
                  <div><span className="text-muted">Power:</span> {fmt(a.total_power)}</div>
                  <div><span className="text-muted">KP:</span> {fmt(a.total_kp)}</div>
                  <div><span className="text-muted">Dead:</span> {fmt(a.total_dead)}</div>
                  <div><span className="text-muted">T4:</span> {fmt(a.total_t4)}</div>
                  <div><span className="text-muted">T5:</span> {fmt(a.total_t5)}</div>
                  <div><span className="text-muted">Avg Power:</span> {fmt(a.avg_power)}</div>
                  {a.top_governor && (
                    <div><span className="text-muted">Top:</span> {a.top_governor.name}</div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="card space-y-3">
              <h2 className="font-semibold">📊 Stat Comparison</h2>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis type="number" stroke="#71717a" tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(v)} />
                    <YAxis type="category" dataKey="stat" stroke="#71717a" tick={{ fontSize: 11 }} width={75} />
                    <Tooltip content={<ChartTooltip />} />
                    <Legend />
                    {compareData.map((a, i) => (
                      <Bar key={a.alliance} dataKey={a.alliance} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card space-y-3">
              <h2 className="font-semibold">🎯 Radar Comparison</h2>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={radarData}>
                    <PolarGrid stroke="#3f3f46" />
                    <PolarAngleAxis dataKey="stat" tick={{ fontSize: 11, fill: "#a1a1aa" }} />
                    <PolarRadiusAxis tick={{ fontSize: 10, fill: "#71717a" }} domain={[0, 100]} />
                    {compareData.map((a, i) => (
                      <Radar key={a.alliance} name={a.alliance} dataKey={a.alliance} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.15} strokeWidth={2} />
                    ))}
                    <Legend />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Stats cards */}
      {!loading && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card">
            <p className="text-muted text-sm mb-1">Total Alliances</p>
            <p className="text-2xl font-bold">{alliances.length}</p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Total Members</p>
            <p className="text-2xl font-bold">
              {alliances.reduce((sum, a) => sum + a.member_count, 0)}
            </p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Combined Power</p>
            <p className="text-2xl font-bold">
              {fmt(alliances.reduce((sum, a) => sum + a.total_power, 0))}
            </p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Combined Kills</p>
            <p className="text-2xl font-bold">
              {fmt(alliances.reduce((sum, a) => sum + a.total_kills, 0))}
            </p>
          </div>
        </div>
      )}

      {/* Table with checkboxes */}
      <div className="card overflow-hidden p-0">
        {selected.size > 0 && (
          <div className="px-4 py-2 bg-blue-500/10 border-b border-blue-500/30 text-sm text-blue-300">
            {selected.size} alliance{selected.size > 1 ? "s" : ""} selected for comparison
            {selected.size < 2 && " (select at least 2)"}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-bg">
                <th className="px-4 py-3 w-8"></th>
                <th className="text-left px-4 py-3 font-medium">Rank</th>
                <th className="text-left px-4 py-3 font-medium">Alliance</th>
                <th className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent" onClick={() => handleSort("member_count")}>
                  Members<SortIcon field="member_count" />
                </th>
                <th className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent" onClick={() => handleSort("total_power")}>
                  Total Power<SortIcon field="total_power" />
                </th>
                <th className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent" onClick={() => handleSort("avg_power")}>
                  Avg Power<SortIcon field="avg_power" />
                </th>
                <th className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent" onClick={() => handleSort("total_kills")}>
                  Total Kill Points<SortIcon field="total_kills" />
                </th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-muted">
                    <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
                  </td>
                </tr>
              ) : sortedAlliances.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-muted">No alliances found</td>
                </tr>
              ) : (
                sortedAlliances.map((alliance, idx) => (
                  <tr
                    key={alliance.alliance}
                    className={`border-b border-border hover:bg-border/50 cursor-pointer ${selected.has(alliance.alliance) ? "bg-blue-500/10" : ""}`}
                    onClick={() => toggleSelect(alliance.alliance)}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(alliance.alliance)}
                        onChange={() => toggleSelect(alliance.alliance)}
                        className="rounded"
                      />
                    </td>
                    <td className="px-4 py-3 text-muted">{idx + 1}</td>
                    <td className="px-4 py-3">
                      <span className="px-3 py-1 bg-accent/20 text-accent rounded font-medium">
                        {alliance.alliance}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{alliance.member_count}</td>
                    <td className="px-4 py-3 text-right font-mono">{fmt(alliance.total_power)}</td>
                    <td className="px-4 py-3 text-right font-mono">{fmt(alliance.avg_power)}</td>
                    <td className="px-4 py-3 text-right font-mono">{fmt(alliance.total_kills)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
