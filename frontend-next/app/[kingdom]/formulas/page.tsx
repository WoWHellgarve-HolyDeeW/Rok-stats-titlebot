"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

interface Formula {
  id: number;
  name: string;
  expression: string;
  description: string | null;
  created_at: string;
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

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const fetchFormulas = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/dkp-formulas`);
      if (res.ok) {
        const data = await res.json();
        setFormulas(data);
      }
    } catch (err) {
      console.error("Failed to fetch formulas:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFormulas();
  }, [apiBase, kdNum]);

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
    if (!confirm("Are you sure you want to delete this formula?")) return;

    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/dkp-formulas/${id}`, {
        method: "DELETE",
      });

      if (res.ok) {
        setSuccess("Formula deleted successfully!");
        fetchFormulas();
      } else {
        setError("Failed to delete formula");
      }
    } catch (err) {
      setError("Failed to delete formula");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">DKP Formulas</h1>
          <p className="text-muted">Configure DKP calculation formulas for your kingdom</p>
        </div>

        <button
          onClick={() => setShowCreate(!showCreate)}
          className="btn"
        >
          {showCreate ? "Cancel" : "+ New Formula"}
        </button>
      </div>

      {/* Messages */}
      {error && (
        <div className="bg-red-500/20 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-500/20 border border-green-500/50 text-green-400 px-4 py-3 rounded-lg">
          {success}
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="card">
          <h3 className="text-lg font-semibold mb-4">Create New Formula</h3>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="block text-sm text-muted mb-1">Formula Name</label>
              <input
                type="text"
                value={newFormula.name}
                onChange={(e) => setNewFormula({ ...newFormula, name: e.target.value })}
                placeholder="e.g., KvK DKP"
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
                required
              />
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">Expression</label>
              <textarea
                value={newFormula.expression}
                onChange={(e) => setNewFormula({ ...newFormula, expression: e.target.value })}
                placeholder="e.g., (t4_kills * 10) + (t5_kills * 20) + (dead * 5)"
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent h-24 font-mono text-sm"
                required
              />
              <p className="text-xs text-muted mt-1">
                Available variables: power, kill_points, t4_kills, t5_kills, dead
              </p>
            </div>
            <div>
              <label className="block text-sm text-muted mb-1">Description (optional)</label>
              <input
                type="text"
                value={newFormula.description}
                onChange={(e) => setNewFormula({ ...newFormula, description: e.target.value })}
                placeholder="Describe this formula..."
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
              />
            </div>
            <button type="submit" className="btn">
              Create Formula
            </button>
          </form>
        </div>
      )}

      {/* Formulas list */}
      <div className="grid gap-4">
        {loading ? (
          <div className="card text-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
            Loading...
          </div>
        ) : formulas.length === 0 ? (
          <div className="card text-center py-12 text-muted">
            <div className="text-4xl mb-2">📊</div>
            <p>No formulas configured yet.</p>
            <p className="text-sm">Create your first DKP formula to get started!</p>
          </div>
        ) : (
          formulas.map((formula) => (
            <div key={formula.id} className="card">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-semibold">{formula.name}</h3>
                  {formula.description && (
                    <p className="text-muted text-sm mt-1">{formula.description}</p>
                  )}
                  <div className="mt-3 bg-bg rounded-lg px-4 py-2 font-mono text-sm text-accent overflow-x-auto">
                    {formula.expression}
                  </div>
                  <p className="text-xs text-muted mt-2">
                    Created: {new Date(formula.created_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  onClick={() => handleDelete(formula.id)}
                  className="p-2 text-muted hover:text-red-400 transition-colors"
                  title="Delete formula"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Help section */}
      <div className="card bg-accent/5 border-accent/20">
        <h3 className="font-semibold mb-3">Formula Help</h3>
        <div className="text-sm text-muted space-y-2">
          <p><strong>Available Variables:</strong></p>
          <ul className="list-disc list-inside ml-2 space-y-1">
            <li><code className="text-accent">power</code> - Player's total power</li>
            <li><code className="text-accent">kill_points</code> - Total kill points</li>
            <li><code className="text-accent">t4_kills</code> - Tier 4 kills count</li>
            <li><code className="text-accent">t5_kills</code> - Tier 5 kills count</li>
            <li><code className="text-accent">dead</code> - Dead troops count</li>
          </ul>
          <p className="mt-3"><strong>Example Formulas:</strong></p>
          <ul className="list-disc list-inside ml-2 space-y-1">
            <li><code className="text-accent">(t4_kills * 10) + (t5_kills * 20)</code></li>
            <li><code className="text-accent">(dead * 5) + (kill_points / 1000)</code></li>
            <li><code className="text-accent">t5_kills * 25 + dead * 3</code></li>
          </ul>
        </div>
      </div>
    </div>
  );
}
