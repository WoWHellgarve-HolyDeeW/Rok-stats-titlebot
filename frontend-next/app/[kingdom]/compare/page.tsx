"use client";
import { useParams } from "next/navigation";
import { useState, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import { fmt, fmtFull } from "@/components/format";
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
          <span className="font-bold text-white">{fmtFull(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

interface GovernorData {
  governor_id: number;
  name: string;
  alliance: string | null;
  kingdom: number | null;
  latest: Record<string, any> | null;
  deltas: Record<string, number>;
  profile: Record<string, any> | null;
}

export default function ComparePage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  const [inputIds, setInputIds] = useState("");
  const [governors, setGovernors] = useState<GovernorData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Name search autocomplete
  const [nameQuery, setNameQuery] = useState("");
  const [suggestions, setSuggestions] = useState<{ governor_id: number; name: string; alliance: string | null }[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIds, setSelectedIds] = useState<{ id: number; name: string }[]>([]);
  const nameRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  // Close suggestions on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (nameRef.current && !nameRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const searchGovernors = useCallback(
    (q: string) => {
      if (q.length < 2) { setSuggestions([]); return; }
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(async () => {
        try {
          const res = await fetch(
            `${apiBase}/kingdoms/${kdNum}/governors?search=${encodeURIComponent(q)}&limit=8&skip=0&sort_by=power&sort_dir=desc`
          );
          if (res.ok) {
            const data = await res.json();
            setSuggestions(
              (data.items || []).map((g: any) => ({
                governor_id: g.governor_id,
                name: g.name,
                alliance: g.alliance,
              }))
            );
            setShowSuggestions(true);
          }
        } catch { /* ignore */ }
      }, 250);
    },
    [apiBase, kdNum]
  );

  const addGovernor = (id: number, name: string) => {
    if (selectedIds.length >= 6) return;
    if (selectedIds.some((s) => s.id === id)) return;
    const next = [...selectedIds, { id, name }];
    setSelectedIds(next);
    setInputIds(next.map((s) => s.id).join(", "));
    setNameQuery("");
    setSuggestions([]);
    setShowSuggestions(false);
  };

  const removeGovernor = (id: number) => {
    const next = selectedIds.filter((s) => s.id !== id);
    setSelectedIds(next);
    setInputIds(next.map((s) => s.id).join(", "));
  };

  const handleCompare = useCallback(async () => {
    const ids = inputIds
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (ids.length < 2) {
      setError("Enter at least 2 governor IDs");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${apiBase}/compare/governors?ids=${ids.join(",")}`);
      if (!res.ok) throw new Error("Failed to fetch");
      const data = await res.json();
      setGovernors(data.governors || []);
      if (data.governors.length < 2) setError("Not enough governors found");
    } catch {
      setError("Failed to load governors. Check IDs.");
    } finally {
      setLoading(false);
    }
  }, [inputIds, apiBase]);

  // Prepare bar chart data
  const statKeys = ["power", "kill_points", "t4_kills", "t5_kills", "dead"];
  const statLabels: Record<string, string> = {
    power: "Power",
    kill_points: "Kill Points",
    t4_kills: "T4 Kills",
    t5_kills: "T5 Kills",
    dead: "Dead",
  };

  const barData = statKeys.map((key) => {
    const row: Record<string, any> = { stat: statLabels[key] };
    governors.forEach((g) => {
      row[g.name] = g.latest?.[key] ?? 0;
    });
    return row;
  });

  // Radar chart data (normalized 0-100)
  const radarKeys = ["power", "kill_points", "t4_kills", "t5_kills", "dead"];
  const maxVals: Record<string, number> = {};
  radarKeys.forEach((k) => {
    maxVals[k] = Math.max(1, ...governors.map((g) => g.latest?.[k] ?? 0));
  });
  const radarData = radarKeys.map((k) => {
    const row: Record<string, any> = { stat: statLabels[k] };
    governors.forEach((g) => {
      row[g.name] = Math.round(((g.latest?.[k] ?? 0) / maxVals[k]) * 100);
    });
    return row;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">⚖️ Governor Comparison</h1>
        <p className="text-muted">Compare 2-6 governors side by side</p>
      </div>

      {/* Input */}
      <div className="card space-y-4">
        <div>
          <label className="block text-sm text-muted mb-2">Governor IDs (comma separated)</label>
          <div className="flex gap-3">
            <input
              type="text"
              value={inputIds}
              onChange={(e) => setInputIds(e.target.value)}
              placeholder="e.g. 123456789, 987654321"
              className="flex-1 px-4 py-2 rounded-lg bg-zinc-800 border border-zinc-700 focus:border-blue-500 outline-none text-sm"
              onKeyDown={(e) => e.key === "Enter" && handleCompare()}
            />
            <button onClick={handleCompare} disabled={loading} className="btn">
              {loading ? "Loading…" : "Compare"}
            </button>
          </div>
        </div>

        {/* Name search */}
        <div ref={nameRef} className="relative">
          <label className="block text-sm text-muted mb-2">Or search by name</label>
          <input
            type="text"
            value={nameQuery}
            onChange={(e) => { setNameQuery(e.target.value); searchGovernors(e.target.value); }}
            placeholder="Type governor name..."
            className="w-full px-4 py-2 rounded-lg bg-zinc-800 border border-zinc-700 focus:border-blue-500 outline-none text-sm"
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
          />
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-20 mt-1 w-full bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl max-h-56 overflow-y-auto">
              {suggestions.map((s) => (
                <button
                  key={s.governor_id}
                  onClick={() => addGovernor(s.governor_id, s.name)}
                  className="w-full text-left px-4 py-2 hover:bg-zinc-800 text-sm flex justify-between items-center"
                >
                  <span>{s.name}</span>
                  <span className="text-xs text-muted">[{s.alliance ?? "—"}] · {s.governor_id}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Selected governors chips */}
        {selectedIds.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {selectedIds.map((s) => (
              <span key={s.id} className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-blue-500/20 text-blue-300 text-xs font-medium">
                {s.name} ({s.id})
                <button onClick={() => removeGovernor(s.id)} className="ml-1 hover:text-red-400">×</button>
              </span>
            ))}
          </div>
        )}

        {error && <p className="text-red-400 text-sm">{error}</p>}
      </div>

      {governors.length >= 2 && (
        <>
          {/* Stat Cards Side-by-Side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {governors.map((g, i) => (
              <div key={g.governor_id} className="card space-y-3" style={{ borderLeft: `3px solid ${COLORS[i % COLORS.length]}` }}>
                <div className="flex items-center gap-2">
                  <div
                    className="w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm"
                    style={{ backgroundColor: COLORS[i % COLORS.length] + "30", color: COLORS[i % COLORS.length] }}
                  >
                    {i + 1}
                  </div>
                  <div>
                    <Link href={`/governors/${g.governor_id}`} className="font-semibold hover:text-blue-400 transition-colors">
                      {g.name}
                    </Link>
                    <div className="text-xs text-muted">
                      [{g.alliance ?? "N/A"}] · ID: {g.governor_id}
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><span className="text-muted">Power:</span> <span className="font-medium">{fmt(g.latest?.power)}</span></div>
                  <div><span className="text-muted">KP:</span> <span className="font-medium">{fmt(g.latest?.kill_points)}</span></div>
                  <div><span className="text-muted">T4:</span> <span className="font-medium">{fmt(g.latest?.t4_kills)}</span></div>
                  <div><span className="text-muted">T5:</span> <span className="font-medium">{fmt(g.latest?.t5_kills)}</span></div>
                  <div><span className="text-muted">Dead:</span> <span className="font-medium">{fmt(g.latest?.dead)}</span></div>
                  <div><span className="text-muted">RSS:</span> <span className="font-medium">{fmt(g.latest?.rss_gathered)}</span></div>
                  {g.profile?.vip_level != null && (
                    <div><span className="text-muted">VIP:</span> <span className="font-medium">{g.profile.vip_level}</span></div>
                  )}
                  {g.profile?.city_hall_level != null && (
                    <div><span className="text-muted">CH:</span> <span className="font-medium">{g.profile.city_hall_level}</span></div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Bar Chart Comparison */}
          <div className="card space-y-4">
            <h2 className="text-lg font-semibold">📊 Stat Comparison</h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis type="number" stroke="#71717a" tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v)} />
                  <YAxis type="category" dataKey="stat" stroke="#71717a" tick={{ fontSize: 11 }} width={85} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend />
                  {governors.map((g, i) => (
                    <Bar key={g.governor_id} dataKey={g.name} fill={COLORS[i % COLORS.length]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Radar Chart */}
          <div className="card space-y-4">
            <h2 className="text-lg font-semibold">🎯 Radar Comparison</h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#3f3f46" />
                  <PolarAngleAxis dataKey="stat" tick={{ fontSize: 11, fill: "#a1a1aa" }} />
                  <PolarRadiusAxis tick={{ fontSize: 10, fill: "#71717a" }} domain={[0, 100]} />
                  {governors.map((g, i) => (
                    <Radar
                      key={g.governor_id}
                      name={g.name}
                      dataKey={g.name}
                      stroke={COLORS[i % COLORS.length]}
                      fill={COLORS[i % COLORS.length]}
                      fillOpacity={0.15}
                      strokeWidth={2}
                    />
                  ))}
                  <Legend />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
