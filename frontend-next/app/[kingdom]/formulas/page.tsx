"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
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
} from "recharts";

interface Formula {
  id: number;
  name: string;
  expression: string;
  description: string | null;
  created_at: string;
}

interface EvalResult {
  governor_id: number;
  name: string;
  alliance: string | null;
  score: number;
  power: number;
  kill_points: number;
  t4_kills: number;
  t5_kills: number;
  dead: number;
}

interface EvalResponse {
  formula: { id: number; name: string; expression: string };
  results: EvalResult[];
  total_evaluated: number;
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 shadow-xl text-xs">
      <div className="text-zinc-400 mb-1">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.fill }} />
          <span className="text-zinc-300">{p.name}:</span>
          <span className="font-bold text-white">{fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export default function FormulasPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;

  const [loading, setLoading] = useState(true);
  const [formulas, setFormulas] = useState<Formula[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newFormula, setNewFormula] = useState({
    name: "",
    expression: "",
    description: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Evaluate state
  const [evalData, setEvalData] = useState<EvalResponse | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalFormulaId, setEvalFormulaId] = useState<number | null>(null);
  const [evalSearch, setEvalSearch] = useState("");
  const [evalSortBy, setEvalSortBy] = useState("score");
  const [evalSortDir, setEvalSortDir] = useState<"asc" | "desc">("desc");

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const fetchFormulas = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/dkp-formulas`);
      if (res.ok) setFormulas(await res.json());
    } catch (err) {
      console.error("Failed to fetch formulas:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchFormulas(); }, [apiBase, kdNum]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/dkp-formulas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newFormula),
      });

      if (res.ok) {
        setSuccess("Formula created successfully!");
        setNewFormula({ name: "", expression: "", description: "" });
        setShowCreate(false);
        fetchFormulas();
      } else {
        const data = await res.json();
        setError(data.detail || "Failed to create formula");
      }
    } catch (err) {
      setError("Failed to create formula");
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this formula?")) return;
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/dkp-formulas/${id}`, { method: "DELETE" });
      if (res.ok) { setSuccess("Deleted"); fetchFormulas(); if (evalFormulaId === id) { setEvalData(null); setEvalFormulaId(null); } }
      else setError("Failed to delete");
    } catch { setError("Failed to delete"); }
  };

  const handleEvaluate = async (formulaId: number) => {
    setEvalLoading(true); setEvalFormulaId(formulaId); setEvalData(null);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/dkp-formulas/${formulaId}/evaluate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 200 }),
      });
      if (res.ok) setEvalData(await res.json());
      else setError("Failed to evaluate");
    } catch { setError("Failed to evaluate"); }
    finally { setEvalLoading(false); }
  };

  const evalFiltered = (evalData?.results ?? [])
    .filter(r => !evalSearch || r.name.toLowerCase().includes(evalSearch.toLowerCase()) || (r.alliance ?? "").toLowerCase().includes(evalSearch.toLowerCase()))
    .sort((a, b) => {
      const va = (a as any)[evalSortBy] ?? 0;
      const vb = (b as any)[evalSortBy] ?? 0;
      return evalSortDir === "desc" ? vb - va : va - vb;
    });

  const EvalSortHeader = ({ field, label }: { field: string; label: string }) => (
    <th className="text-right cursor-pointer hover:text-blue-400 transition-colors select-none px-3 py-2"
      onClick={() => { if (evalSortBy === field) setEvalSortDir(evalSortDir === "desc" ? "asc" : "desc"); else { setEvalSortBy(field); setEvalSortDir("desc"); } }}>
      {label} {evalSortBy === field ? (evalSortDir === "desc" ? "↓" : "↑") : ""}
    </th>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">📊 DKP Formulas</h1>
          <p className="text-muted">Configure and evaluate DKP calculation formulas</p>
        </div>
        <button onClick={() => setShowCreate(!showCreate)} className="btn">{showCreate ? "Cancel" : "+ New Formula"}</button>
      </div>

      {error && <div className="bg-red-500/20 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg">{error}</div>}
      {success && <div className="bg-green-500/20 border border-green-500/50 text-green-400 px-4 py-3 rounded-lg">{success}</div>}

      {showCreate && (
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Create New Formula</h3>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="block text-sm text-muted mb-1">Name</label>
              <input type="text" value={newFormula.name} onChange={(e) => setNewFormula({ ...newFormula, name: e.target.value })}
                placeholder="e.g., KvK DKP" className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent" required />
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">Expression</label>
              <textarea value={newFormula.expression} onChange={(e) => setNewFormula({ ...newFormula, expression: e.target.value })}
                placeholder="(t4_kills * 10) + (t5_kills * 20) + (dead * 5)"
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent h-24 font-mono text-sm" required />
              <p className="text-xs text-muted mt-1">Variables: power, kill_points, t1...t5_kills, dead, acclaims, helps, power_gain, kp_gain, t4_gain, t5_gain, dead_gain</p>
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">Description</label>
              <input type="text" value={newFormula.description} onChange={(e) => setNewFormula({ ...newFormula, description: e.target.value })}
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent" />
            </div>
            <button type="submit" className="btn">Create Formula</button>
          </form>
        </div>
      )}

      {/* Formulas list */}
      <div className="grid gap-4">
        {loading ? (
          <div className="card text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2" />Loading...</div>
        ) : formulas.length === 0 ? (
          <div className="card text-center py-12 text-muted"><div className="text-4xl mb-2">📊</div><p>No formulas yet. Create one!</p></div>
        ) : formulas.map((f) => (
          <div key={f.id} className="card">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-semibold">{f.name}</h3>
                {f.description && <p className="text-muted text-sm mt-1">{f.description}</p>}
                <div className="mt-3 bg-bg rounded-lg px-4 py-2 font-mono text-sm text-accent overflow-x-auto">{f.expression}</div>
                <p className="text-xs text-muted mt-2">Created: {new Date(f.created_at).toLocaleDateString()}</p>
              </div>
              <div className="flex gap-2">
                <button onClick={() => handleEvaluate(f.id)} disabled={evalLoading && evalFormulaId === f.id}
                  className="px-3 py-1.5 text-sm font-medium rounded-lg bg-blue-500/20 text-blue-400 border border-blue-500/30 hover:bg-blue-500/30 transition-colors disabled:opacity-50">
                  {evalLoading && evalFormulaId === f.id ? "..." : "▶ Evaluate"}
                </button>
                <button onClick={() => handleDelete(f.id)} className="p-2 text-muted hover:text-red-400 transition-colors">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Evaluation Results */}
      {evalData && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold">🏆 Results: {evalData.formula.name}</h2>
              <p className="text-muted text-sm"><code className="text-accent">{evalData.formula.expression}</code> · {evalData.total_evaluated} governors</p>
            </div>
            <button onClick={() => { setEvalData(null); setEvalFormulaId(null); }} className="text-sm text-muted hover:text-red-400">✕ Close</button>
          </div>

          <div className="card space-y-3">
            <h3 className="font-semibold">Top 15</h3>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={evalFiltered.slice(0, 15).map(r => ({ name: r.name.length > 14 ? r.name.slice(0, 14) + "…" : r.name, Score: r.score }))} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis type="number" stroke="#71717a" tick={{ fontSize: 10 }} tickFormatter={v => fmt(v)} />
                  <YAxis type="category" dataKey="name" stroke="#71717a" tick={{ fontSize: 10 }} width={110} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="Score" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card space-y-3">
            <div className="flex items-center gap-3">
              <input type="text" value={evalSearch} onChange={e => setEvalSearch(e.target.value)} placeholder="Search..."
                className="flex-1 px-4 py-2 rounded-lg bg-zinc-800 border border-zinc-700 focus:border-blue-500 outline-none text-sm" />
              <span className="text-sm text-muted">{evalFiltered.length} governors</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm table">
                <thead><tr className="text-muted text-xs">
                  <th className="text-left w-8 px-3 py-2">#</th>
                  <th className="text-left px-3 py-2">Governor</th>
                  <th className="text-left px-3 py-2">Alliance</th>
                  <EvalSortHeader field="score" label="Score" />
                  <EvalSortHeader field="power" label="Power" />
                  <EvalSortHeader field="kill_points" label="KP" />
                  <EvalSortHeader field="t4_kills" label="T4" />
                  <EvalSortHeader field="t5_kills" label="T5" />
                  <EvalSortHeader field="dead" label="Dead" />
                </tr></thead>
                <tbody>
                  {evalFiltered.slice(0, 100).map((r, i) => (
                    <tr key={r.governor_id} className="hover:bg-[#0d1626] border-t border-zinc-800">
                      <td className="text-muted px-3 py-1.5">{i + 1}</td>
                      <td className="px-3 py-1.5"><Link href={`/governors/${r.governor_id}`} className="text-blue-400 hover:underline">{r.name}</Link></td>
                      <td className="text-muted px-3 py-1.5">{r.alliance ?? "—"}</td>
                      <td className="text-right font-bold text-yellow-400 px-3 py-1.5">{fmt(r.score)}</td>
                      <td className="text-right px-3 py-1.5">{fmt(r.power)}</td>
                      <td className="text-right px-3 py-1.5">{fmt(r.kill_points)}</td>
                      <td className="text-right text-purple-400 px-3 py-1.5">{fmt(r.t4_kills)}</td>
                      <td className="text-right text-pink-400 px-3 py-1.5">{fmt(r.t5_kills)}</td>
                      <td className="text-right text-red-400 px-3 py-1.5">{fmt(r.dead)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Help */}
      <div className="card bg-accent/5 border-accent/20">
        <h3 className="font-semibold mb-3">Formula Help</h3>
        <div className="text-sm text-muted space-y-2">
          <p><strong>Variables:</strong> power, kill_points, t1...t5_kills, dead, acclaims, highest_acclaims, rss_gathered, helps, power_gain, kp_gain, t4_gain, t5_gain, dead_gain</p>
          <p><strong>Examples:</strong></p>
          <ul className="list-disc list-inside ml-2 space-y-1 text-xs">
            <li><code className="text-accent">(t4_kills * 10) + (t5_kills * 20) + (dead * 5)</code></li>
            <li><code className="text-accent">t5_kills * 25 + dead * 3 - power * 0.001</code></li>
            <li><code className="text-accent">(kp_gain / 1000) + (dead_gain * 2)</code></li>
          </ul>
        </div>
      </div>
    </div>
  );
}
