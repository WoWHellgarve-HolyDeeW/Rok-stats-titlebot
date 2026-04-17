"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { fmt, fmtSigned } from "@/components/format";
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
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
} from "recharts";

const COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316"];

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

interface KvkData {
  kvk: { kvk_active: string | null; kvk_start: string | null; kvk_end: string | null; war_periods: { index: number; label: string; start: string | null; end: string | null; configured: boolean }[] };
  calculation_mode?: string;
  totals: Record<string, number>;
  governors: any[];
}

interface KvkKingdom {
  id: number;
  kingdom_number: number;
  kingdom_name: string | null;
  side: number | null;
  is_home: boolean;
  total_power: number | null;
  total_kp: number | null;
  total_dead: number | null;
  total_t4_kills: number | null;
  total_t5_kills: number | null;
  governor_count: number | null;
  avg_power: number | null;
  kp_gain: number | null;
  dead_gain: number | null;
  t4_gain: number | null;
  t5_gain: number | null;
  notes: string | null;
}

interface KvkGroup {
  id: number;
  name: string;
  kvk_code: string | null;
  season: string | null;
  started_at: string | null;
  ended_at: string | null;
  notes: string | null;
  created_at: string;
  kingdoms: KvkKingdom[];
}

type TabId = "kingdom" | "multi";

export default function KvKPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const [activeTab, setActiveTab] = useState<TabId>("kingdom");
  const [data, setData] = useState<KvkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState("dkp");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [search, setSearch] = useState("");

  // Multi-kingdom state
  const [groups, setGroups] = useState<KvkGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [newGroup, setNewGroup] = useState({ name: "", kvk_code: "", season: "", started_at: "", ended_at: "" });
  const [opponents, setOpponents] = useState<{ kingdom_number: string; kingdom_name: string; side: string }[]>([]);
  const [groupMsg, setGroupMsg] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/kvk`);
      if (!res.ok) throw new Error("Failed");
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, kdNum]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const fetchGroups = useCallback(async () => {
    setGroupsLoading(true);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/kvk-groups`);
      if (res.ok) setGroups(await res.json());
    } catch { /* ignore */ }
    finally { setGroupsLoading(false); }
  }, [apiBase, kdNum]);

  useEffect(() => { if (activeTab === "multi") fetchGroups(); }, [activeTab, fetchGroups]);

  const handleCreateGroup = async () => {
    if (!newGroup.name.trim()) return;
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/kvk-groups`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...newGroup,
          home_side: 1,
          opponents: opponents.filter(o => o.kingdom_number).map(o => ({
            kingdom_number: parseInt(o.kingdom_number),
            kingdom_name: o.kingdom_name,
            side: parseInt(o.side) || 2,
          })),
        }),
      });
      if (res.ok) {
        setGroupMsg("KvK group created!");
        setShowCreateGroup(false);
        setNewGroup({ name: "", kvk_code: "", season: "", started_at: "", ended_at: "" });
        setOpponents([]);
        fetchGroups();
      }
    } catch { setGroupMsg("Failed to create group"); }
  };

  const handleAutoStats = async (groupId: number) => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/kvk-groups/${groupId}/auto-stats`, { method: "POST" });
      if (res.ok) { setGroupMsg("Stats updated!"); fetchGroups(); }
    } catch { setGroupMsg("Failed to update stats"); }
  };

  const handleDeleteGroup = async (groupId: number) => {
    if (!confirm("Delete this KvK group?")) return;
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/kvk-groups/${groupId}`, { method: "DELETE" });
      if (res.ok) { setGroupMsg("Group deleted"); fetchGroups(); }
    } catch { setGroupMsg("Failed to delete"); }
  };

  // Sort & filter for kingdom tab
  let filtered = (data?.governors ?? []).filter(
    (g: any) =>
      !search ||
      g.name.toLowerCase().includes(search.toLowerCase()) ||
      (g.alliance ?? "").toLowerCase().includes(search.toLowerCase())
  );
  filtered.sort((a: any, b: any) => {
    const va = a[sortBy] ?? 0;
    const vb = b[sortBy] ?? 0;
    return sortDir === "desc" ? vb - va : va - vb;
  });

  // Alliance breakdown for pie chart
  const allianceMap: Record<string, { kp: number; dead: number; t4: number; t5: number }> = {};
  (data?.governors ?? []).forEach((g: any) => {
    const a = g.alliance || "No Alliance";
    if (!allianceMap[a]) allianceMap[a] = { kp: 0, dead: 0, t4: 0, t5: 0 };
    allianceMap[a].kp += g.kp_gain;
    allianceMap[a].dead += g.dead_gain;
    allianceMap[a].t4 += g.t4_gain;
    allianceMap[a].t5 += g.t5_gain;
  });
  const pieData = Object.entries(allianceMap)
    .map(([name, v]) => ({ name, value: v.kp + v.dead }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  const SortHeader = ({ field, label }: { field: string; label: string }) => (
    <th
      className="text-right cursor-pointer hover:text-blue-400 transition-colors select-none"
      onClick={() => {
        if (sortBy === field) setSortDir(sortDir === "desc" ? "asc" : "desc");
        else { setSortBy(field); setSortDir("desc"); }
      }}
    >
      {label} {sortBy === field ? (sortDir === "desc" ? "↓" : "↑") : ""}
    </th>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">⚔️ KvK Tracking</h1>
        <div className="flex bg-zinc-800 rounded-lg p-1">
          <button onClick={() => setActiveTab("kingdom")} className={`px-4 py-1.5 text-sm rounded-md transition-all ${activeTab === "kingdom" ? "bg-zinc-600 text-white font-medium" : "text-zinc-400 hover:text-zinc-200"}`}>
            Kingdom KvK
          </button>
          <button onClick={() => setActiveTab("multi")} className={`px-4 py-1.5 text-sm rounded-md transition-all ${activeTab === "multi" ? "bg-zinc-600 text-white font-medium" : "text-zinc-400 hover:text-zinc-200"}`}>
            Multi-Kingdom
          </button>
        </div>
      </div>

      {/* ═══ Multi-Kingdom Tab ═══ */}
      {activeTab === "multi" && (
        <div className="space-y-6">
          {groupMsg && <div className="bg-blue-500/20 border border-blue-500/50 text-blue-400 px-4 py-3 rounded-lg">{groupMsg}</div>}

          <div className="flex justify-end">
            <button onClick={() => setShowCreateGroup(!showCreateGroup)} className="btn">
              {showCreateGroup ? "Cancel" : "+ New KvK Group"}
            </button>
          </div>

          {showCreateGroup && (
            <div className="card space-y-4">
              <h3 className="text-lg font-semibold">Create KvK Group</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <input type="text" value={newGroup.name} onChange={e => setNewGroup({ ...newGroup, name: e.target.value })}
                  placeholder="Group name (e.g., KvK Season 5)" className="bg-bg border border-border rounded-lg px-3 py-2" />
                <input type="text" value={newGroup.kvk_code} onChange={e => setNewGroup({ ...newGroup, kvk_code: e.target.value })}
                  placeholder="KvK code (e.g., c12949)" className="bg-bg border border-border rounded-lg px-3 py-2" />
                <input type="text" value={newGroup.season} onChange={e => setNewGroup({ ...newGroup, season: e.target.value })}
                  placeholder="Season (e.g., 5)" className="bg-bg border border-border rounded-lg px-3 py-2" />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-muted mb-1">Start Date</label>
                  <input type="datetime-local" value={newGroup.started_at} onChange={e => setNewGroup({ ...newGroup, started_at: e.target.value })}
                    className="w-full bg-bg border border-border rounded-lg px-3 py-2" />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">End Date</label>
                  <input type="datetime-local" value={newGroup.ended_at} onChange={e => setNewGroup({ ...newGroup, ended_at: e.target.value })}
                    className="w-full bg-bg border border-border rounded-lg px-3 py-2" />
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold">Opponent Kingdoms</h4>
                  <button onClick={() => setOpponents([...opponents, { kingdom_number: "", kingdom_name: "", side: "2" }])}
                    className="text-xs text-blue-400 hover:text-blue-300">+ Add Opponent</button>
                </div>
                {opponents.map((opp, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input type="number" value={opp.kingdom_number} onChange={e => { const a = [...opponents]; a[i].kingdom_number = e.target.value; setOpponents(a); }}
                      placeholder="KD #" className="w-24 bg-bg border border-border rounded-lg px-3 py-2 text-sm" />
                    <input type="text" value={opp.kingdom_name} onChange={e => { const a = [...opponents]; a[i].kingdom_name = e.target.value; setOpponents(a); }}
                      placeholder="Name" className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm" />
                    <select value={opp.side} onChange={e => { const a = [...opponents]; a[i].side = e.target.value; setOpponents(a); }}
                      className="bg-bg border border-border rounded-lg px-3 py-2 text-sm">
                      <option value="1">Side A</option>
                      <option value="2">Side B</option>
                      <option value="3">Side C</option>
                    </select>
                    <button onClick={() => setOpponents(opponents.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-300 text-sm">✕</button>
                  </div>
                ))}
              </div>
              <button onClick={handleCreateGroup} className="btn">Create Group</button>
            </div>
          )}

          {groupsLoading ? (
            <div className="card text-center py-12"><div className="animate-spin h-8 w-8 border-2 border-blue-400 border-t-transparent rounded-full mx-auto" /></div>
          ) : groups.length === 0 ? (
            <div className="card text-center py-12 text-muted">
              <div className="text-4xl mb-2">🌍</div>
              <p>No KvK groups created yet.</p>
              <p className="text-sm">Create a group to track multiple kingdoms in a KvK!</p>
            </div>
          ) : groups.map(g => (
            <div key={g.id} className="card space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-lg font-semibold">{g.name}</h3>
                  <p className="text-sm text-muted">
                    {g.kvk_code && <>Code: {g.kvk_code} · </>}
                    {g.season && <>Season {g.season} · </>}
                    {g.started_at && <>{g.started_at.split("T")[0]} → {g.ended_at?.split("T")[0] ?? "ongoing"}</>}
                    {" · "}{g.kingdoms.length} kingdoms
                  </p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => handleAutoStats(g.id)} className="px-3 py-1 text-xs bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/30">
                    ↻ Auto Stats
                  </button>
                  <button onClick={() => handleDeleteGroup(g.id)} className="px-3 py-1 text-xs text-red-400 hover:text-red-300">Delete</button>
                </div>
              </div>

              {/* Kingdom comparison cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {g.kingdoms.map(k => (
                  <div key={k.id} className={`rounded-lg border p-4 space-y-3 ${k.is_home ? "border-blue-500/40 bg-blue-500/5" : "border-zinc-700 bg-zinc-800/50"}`}>
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-bold text-lg">KD {k.kingdom_number}</span>
                        {k.kingdom_name && <span className="text-muted text-sm ml-2">{k.kingdom_name}</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        {k.is_home && <span className="text-xs bg-blue-500/20 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded">HOME</span>}
                        <span className="text-xs bg-zinc-700 text-zinc-300 px-2 py-0.5 rounded">Side {k.side ?? "?"}</span>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div><span className="text-muted text-xs">Total Power</span><div className="font-bold text-blue-400">{fmt(k.total_power)}</div></div>
                      <div><span className="text-muted text-xs">Governors</span><div className="font-bold">{k.governor_count ?? "—"}</div></div>
                      <div><span className="text-muted text-xs">Total KP</span><div className="font-bold text-red-400">{fmt(k.total_kp)}</div></div>
                      <div><span className="text-muted text-xs">Total Dead</span><div className="font-bold text-amber-400">{fmt(k.total_dead)}</div></div>
                      <div><span className="text-muted text-xs">T4 Kills</span><div className="text-purple-400">{fmt(k.total_t4_kills)}</div></div>
                      <div><span className="text-muted text-xs">T5 Kills</span><div className="text-pink-400">{fmt(k.total_t5_kills)}</div></div>
                      {k.avg_power && <div><span className="text-muted text-xs">Avg Power</span><div>{fmt(k.avg_power)}</div></div>}
                    </div>
                    {(k.kp_gain || k.dead_gain) && (
                      <div className="grid grid-cols-2 gap-2 text-xs border-t border-zinc-700 pt-2">
                        <div>KP Gain: <span className="text-green-400">{fmtSigned(k.kp_gain)}</span></div>
                        <div>Dead Gain: <span className="text-red-400">{fmtSigned(k.dead_gain)}</span></div>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Multi-kingdom comparison chart */}
              {g.kingdoms.length > 1 && (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={g.kingdoms.map(k => ({ name: `KD ${k.kingdom_number}`, Power: k.total_power ?? 0, KP: k.total_kp ?? 0, Dead: k.total_dead ?? 0 }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="name" stroke="#71717a" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#71717a" tick={{ fontSize: 10 }} tickFormatter={v => fmt(v)} />
                      <Tooltip content={<ChartTooltip />} />
                      <Legend />
                      <Bar dataKey="Power" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="KP" fill="#ef4444" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="Dead" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ═══ Kingdom KvK Tab ═══ */}
      {activeTab === "kingdom" && (loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin h-8 w-8 border-2 border-blue-400 border-t-transparent rounded-full" />
        </div>
      ) : !data || !data.governors?.length ? (
        <div className="card text-muted">
          <p>No KvK data available. Set KvK dates in admin panel to start tracking.</p>
          {data?.kvk?.kvk_active && <p className="mt-2">KvK Code: {data.kvk.kvk_active}</p>}
        </div>
      ) : (<div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">⚔️ KvK Tracking</h1>
          <p className="text-muted">
            {data.kvk.kvk_active && <>Code: {data.kvk.kvk_active} · </>}
            {data.kvk.kvk_start && <>Start: {data.kvk.kvk_start.split("T")[0]} · </>}
            {data.kvk.kvk_end && <>End: {data.kvk.kvk_end.split("T")[0]} · </>}
            {data.totals.participant_count} participants
          </p>
        </div>

        {data.calculation_mode === "war_periods" && data.kvk.war_periods?.some((period) => period.configured) && (
          <div className="card bg-amber-500/10 border-amber-500/30 space-y-3">
            <div>
              <h2 className="font-semibold text-amber-300">Configured War Windows</h2>
              <p className="text-sm text-muted">KvK totals below are calculated only from the configured wars, not from the full KvK span.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {data.kvk.war_periods.filter((period) => period.configured).map((period) => (
                <span key={period.index} className="px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200">
                  {period.label}: {period.start?.split("T")[0]} → {period.end?.split("T")[0]}
                </span>
              ))}
            </div>
          </div>
        )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="card">
          <div className="text-xs text-muted uppercase">Total KP Gain</div>
          <div className="text-xl font-bold text-blue-400">{fmt(data.totals.total_kp_gain)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Total Dead</div>
          <div className="text-xl font-bold text-red-400">{fmt(data.totals.total_dead_gain)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">T4 Kills Gain</div>
          <div className="text-xl font-bold text-purple-400">{fmt(data.totals.total_t4_gain)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">T5 Kills Gain</div>
          <div className="text-xl font-bold text-pink-400">{fmt(data.totals.total_t5_gain)}</div>
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase">Participants</div>
          <div className="text-xl font-bold">{data.totals.participant_count}</div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top 15 DKP Bar Chart */}
        <div className="card space-y-3">
          <h2 className="font-semibold">🏆 Top 15 DKP Contributors</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={filtered.slice(0, 15).map((g) => ({
                  name: g.name.length > 12 ? g.name.slice(0, 12) + "…" : g.name,
                  DKP: g.dkp,
                }))}
                layout="vertical"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis type="number" stroke="#71717a" tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(v)} />
                <YAxis type="category" dataKey="name" stroke="#71717a" tick={{ fontSize: 10 }} width={90} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="DKP" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Alliance Contribution Pie */}
        <div className="card space-y-3">
          <h2 className="font-semibold">🏰 Alliance Contribution</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={90}
                  dataKey="value"
                  label={((props: any) => `${props.name} ${((props.percent ?? 0) * 100).toFixed(0)}%`) as any}
                  labelLine={false}
                >
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip content={<ChartTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Search + Table */}
      <div className="card space-y-3">
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search governor or alliance…"
            className="flex-1 px-4 py-2 rounded-lg bg-zinc-800 border border-zinc-700 focus:border-blue-500 outline-none text-sm"
          />
          <span className="text-sm text-muted">{filtered.length} governors</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm table">
            <thead>
              <tr className="text-muted text-xs">
                <th className="text-left w-8">#</th>
                <th className="text-left">Governor</th>
                <th className="text-left">Alliance</th>
                <SortHeader field="power_gain" label="Power Δ" />
                <SortHeader field="kp_gain" label="KP Gain" />
                <SortHeader field="t4_gain" label="T4 Gain" />
                <SortHeader field="t5_gain" label="T5 Gain" />
                <SortHeader field="dead_gain" label="Dead Gain" />
                <SortHeader field="dkp" label="DKP" />
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 100).map((g: any, i: number) => (
                <tr key={g.governor_id} className="hover:bg-[#0d1626] border-t border-zinc-800">
                  <td className="text-muted">{i + 1}</td>
                  <td>
                    <Link href={`/governors/${g.governor_id}`} className="text-blue-400 hover:underline">
                      {g.name}
                    </Link>
                  </td>
                  <td className="text-muted">{g.alliance ?? "—"}</td>
                  <td className={`text-right ${g.power_gain >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {fmtSigned(g.power_gain)}
                  </td>
                  <td className="text-right">{fmt(g.kp_gain)}</td>
                  <td className="text-right">{fmt(g.t4_gain)}</td>
                  <td className="text-right">{fmt(g.t5_gain)}</td>
                  <td className="text-right text-red-400">{fmt(g.dead_gain)}</td>
                  <td className="text-right font-bold">{fmt(g.dkp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      </div>))}
    </div>
  );
}
