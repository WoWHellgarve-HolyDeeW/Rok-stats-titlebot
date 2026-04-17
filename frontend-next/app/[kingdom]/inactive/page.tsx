"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

interface InactivePlayer {
  governor_id: number;
  name: string;
  alliance: string | null;
  last_seen: string;
  days_inactive: number;
  power: number;
}

export default function InactivePage() {
  const params = useParams();
  const kingdom = params.kingdom as string;

  const [loading, setLoading] = useState(true);
  const [players, setPlayers] = useState<InactivePlayer[]>([]);
  const [threshold, setThreshold] = useState(7);

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  useEffect(() => {
    const fetchInactive = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${apiBase}/kingdoms/${kdNum}/inactive?days_threshold=${threshold}`);
        if (res.ok) {
          const data = await res.json();
          setPlayers(data);
        }
      } catch (err) {
        console.error("Failed to fetch inactive:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchInactive();
  }, [apiBase, kdNum, threshold]);

  const formatNumber = (n: number | null | undefined) => {
    if (n == null) return "0";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toLocaleString();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Inactivity Tracker</h1>
          <p className="text-muted">Monitor inactive players in your kingdom</p>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-muted">Inactive for:</label>
          <select
            value={threshold}
            onChange={(e) => setThreshold(parseInt(e.target.value))}
            className="bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
          >
            <option value={3}>3+ days</option>
            <option value={7}>7+ days</option>
            <option value={14}>14+ days</option>
            <option value={30}>30+ days</option>
          </select>
        </div>
      </div>

      {/* Stats */}
      {!loading && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card">
            <p className="text-muted text-sm mb-1">Inactive Players</p>
            <p className="text-2xl font-bold text-red-400">{players.length}</p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Power at Risk</p>
            <p className="text-2xl font-bold text-amber-400">
              {formatNumber(players.reduce((sum, p) => sum + p.power, 0))}
            </p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Avg Days Inactive</p>
            <p className="text-2xl font-bold">
              {players.length > 0
                ? Math.round(players.reduce((sum, p) => sum + p.days_inactive, 0) / players.length)
                : 0}
            </p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Threshold</p>
            <p className="text-2xl font-bold">{threshold}+ days</p>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-bg">
                <th className="text-left px-4 py-3 font-medium">#</th>
                <th className="text-left px-4 py-3 font-medium">Name</th>
                <th className="text-left px-4 py-3 font-medium">Alliance</th>
                <th className="text-right px-4 py-3 font-medium">Power</th>
                <th className="text-right px-4 py-3 font-medium">Days Inactive</th>
                <th className="text-right px-4 py-3 font-medium">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-muted">
                    <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
                    Loading...
                  </td>
                </tr>
              ) : players.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-muted">
                    <div className="text-4xl mb-2">🎉</div>
                    No inactive players found!
                  </td>
                </tr>
              ) : (
                players.map((player, idx) => (
                  <tr key={player.governor_id} className="border-b border-border hover:bg-border/50">
                    <td className="px-4 py-3 text-muted">{idx + 1}</td>
                    <td className="px-4 py-3 font-medium">{player.name}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-1 bg-accent/20 text-accent rounded text-xs">
                        {player.alliance || "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{formatNumber(player.power)}</td>
                    <td className="px-4 py-3 text-right">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${
                        player.days_inactive >= 30 
                          ? "bg-red-500/20 text-red-400"
                          : player.days_inactive >= 14
                          ? "bg-amber-500/20 text-amber-400"
                          : "bg-yellow-500/20 text-yellow-400"
                      }`}>
                        {player.days_inactive} days
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-muted">
                      {new Date(player.last_seen).toLocaleDateString()}
                    </td>
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
