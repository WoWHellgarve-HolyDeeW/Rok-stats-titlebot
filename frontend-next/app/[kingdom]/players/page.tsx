"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";

interface Governor {
  governor_id: number;
  name: string;
  power: number;
  kill_points: number;
  t4_kills: number;
  t5_kills: number;
  dead: number;
  alliance: string | null;
  scanned_at: string;
  is_banned?: boolean;
  ban_reason?: string | null;
}

interface Ban {
  id: number;
  governor_id: number;
  governor_name: string;
  ban_type: string;
  reason: string | null;
  banned_by: string | null;
  created_at: string;
  expires_at: string | null;
}

interface NameChange {
  governor_id: number;
  old_name: string;
  new_name: string;
  changed_at: string;
  current_alliance: string | null;
}

export default function PlayersPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;

  const [loading, setLoading] = useState(true);
  const [governors, setGovernors] = useState<Governor[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [search, setSearch] = useState("");
  const [alliance, setAlliance] = useState("");
  const [sortBy, setSortBy] = useState("power");
  const [sortDir, setSortDir] = useState("desc");
  const [page, setPage] = useState(1);
  
  // Ban modal state
  const [showBanModal, setShowBanModal] = useState(false);
  const [selectedPlayer, setSelectedPlayer] = useState<Governor | null>(null);
  const [banReason, setBanReason] = useState("");
  const [banExpires, setBanExpires] = useState<number | "">("");
  
  // Bans list
  const [bans, setBans] = useState<Ban[]>([]);
  
  // Name changes
  const [nameChanges, setNameChanges] = useState<NameChange[]>([]);
  const [nameChangesLoading, setNameChangesLoading] = useState(false);
  
  // Tab state: 'players' | 'bans' | 'nameChanges'
  const [activeTab, setActiveTab] = useState<'players' | 'bans' | 'nameChanges'>('players');

  const limit = 25;
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        skip: ((page - 1) * limit).toString(),
        limit: limit.toString(),
        sort_by: sortBy,
        sort_dir: sortDir,
      });
      if (search) params.set("search", search);
      if (alliance) params.set("alliance", alliance);

      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/governors?${params}`);
      if (res.ok) {
        const data = await res.json();
        setGovernors(data.items || []);
        setTotalCount(data.total || 0);
      }
    } catch (err) {
      console.error("Failed to fetch:", err);
    } finally {
      setLoading(false);
    }
  }, [page, sortBy, sortDir, search, alliance, apiBase, kdNum]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Fetch bans
  const fetchBans = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/bans`);
      if (res.ok) {
        const data = await res.json();
        setBans(data || []);
      }
    } catch (err) {
      console.error("Failed to fetch bans:", err);
    }
  }, [apiBase, kdNum]);

  useEffect(() => {
    fetchBans();
  }, [fetchBans]);

  // Fetch name changes
  const fetchNameChanges = useCallback(async () => {
    setNameChangesLoading(true);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/name-changes?limit=100`);
      if (res.ok) {
        const data = await res.json();
        setNameChanges(data.items || []);
      }
    } catch (err) {
      console.error("Failed to fetch name changes:", err);
    } finally {
      setNameChangesLoading(false);
    }
  }, [apiBase, kdNum]);

  useEffect(() => {
    if (activeTab === 'nameChanges') {
      fetchNameChanges();
    }
  }, [activeTab, fetchNameChanges]);

  // Ban a player
  const handleBan = async () => {
    if (!selectedPlayer) return;
    try {
      const params = new URLSearchParams({
        governor_id: selectedPlayer.governor_id.toString(),
        governor_name: selectedPlayer.name,
        ban_type: "titles",
      });
      if (banReason) params.set("reason", banReason);
      if (banExpires) params.set("expires_days", banExpires.toString());

      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/bans?${params}`, {
        method: "POST",
      });
      if (res.ok) {
        setShowBanModal(false);
        setSelectedPlayer(null);
        setBanReason("");
        setBanExpires("");
        fetchData();
        fetchBans();
      }
    } catch (err) {
      console.error("Failed to ban:", err);
    }
  };

  // Remove ban
  const handleUnban = async (banId: number) => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/bans/${banId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        fetchData();
        fetchBans();
      }
    } catch (err) {
      console.error("Failed to unban:", err);
    }
  };

  // Quick unban by governor
  const handleUnbanByGovernor = async (governorId: number) => {
    const ban = bans.find(b => b.governor_id === governorId);
    if (ban) {
      await handleUnban(ban.id);
    }
  };

  const formatNumber = (n: number | null | undefined) => {
    if (n == null) return "0";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toLocaleString();
  };

  const handleSort = (field: string) => {
    if (sortBy === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setSortDir("desc");
    }
    setPage(1);
  };

  const SortIcon = ({ field }: { field: string }) => (
    <span className="ml-1 opacity-50">
      {sortBy === field ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </span>
  );

  const totalPages = Math.ceil(totalCount / limit);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
        <div>
          <h1 className="text-2xl font-bold">Player Management</h1>
          <p className="text-muted">Manage players and title bans</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setActiveTab('players')}
            className={`px-3 py-2 text-sm rounded-lg ${activeTab === 'players' ? 'bg-accent text-white' : 'bg-bg border border-border'}`}
          >
            All Players
          </button>
          <button
            onClick={() => setActiveTab('nameChanges')}
            className={`px-3 py-2 text-sm rounded-lg flex items-center gap-1 ${activeTab === 'nameChanges' ? 'bg-yellow-500 text-white' : 'bg-bg border border-border text-yellow-400'}`}
          >
            <span>✏️</span> Names ({nameChanges.length})
          </button>
          <button
            onClick={() => setActiveTab('bans')}
            className={`px-3 py-2 text-sm rounded-lg flex items-center gap-1 ${activeTab === 'bans' ? 'bg-red-500 text-white' : 'bg-bg border border-border text-red-400'}`}
          >
            <span>🚫</span> Banned ({bans.length})
          </button>
        </div>
      </div>

      {/* Ban Modal */}
      {showBanModal && selectedPlayer && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card border border-border rounded-xl p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4">Ban Player</h2>
            <p className="mb-4">
              Ban <strong>{selectedPlayer.name}</strong> (ID: {selectedPlayer.governor_id}) from receiving titles?
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-muted mb-1">Reason (optional)</label>
                <input
                  type="text"
                  value={banReason}
                  onChange={(e) => setBanReason(e.target.value)}
                  placeholder="e.g., Inactive, Rule violation..."
                  className="w-full bg-bg border border-border rounded-lg px-3 py-2"
                />
              </div>
              <div>
                <label className="block text-sm text-muted mb-1">Expires in (days, leave empty for permanent)</label>
                <input
                  type="number"
                  value={banExpires}
                  onChange={(e) => setBanExpires(e.target.value ? parseInt(e.target.value) : "")}
                  placeholder="Permanent"
                  min={1}
                  className="w-full bg-bg border border-border rounded-lg px-3 py-2"
                />
              </div>
            </div>
            <div className="flex gap-2 mt-6">
              <button
                onClick={() => { setShowBanModal(false); setSelectedPlayer(null); }}
                className="flex-1 px-4 py-2 border border-border rounded-lg hover:bg-border"
              >
                Cancel
              </button>
              <button
                onClick={handleBan}
                className="flex-1 px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
              >
                🚫 Ban Player
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Name Changes Tab */}
      {activeTab === 'nameChanges' ? (
        <div className="card">
          <h3 className="font-bold mb-4">Recent Name Changes</h3>
          <p className="text-sm text-muted mb-4">Players who changed their in-game name (detected when comparing scans)</p>
          {nameChangesLoading ? (
            <div className="text-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
              Loading...
            </div>
          ) : nameChanges.length === 0 ? (
            <p className="text-muted py-8 text-center">No name changes detected yet. Upload multiple scans to detect changes.</p>
          ) : (
            <div className="overflow-x-auto -mx-4 sm:mx-0">
              <table className="w-full text-sm min-w-[600px]">
                <thead>
                  <tr className="border-b border-border bg-bg">
                    <th className="text-left px-4 py-3 font-medium">ID</th>
                    <th className="text-left px-4 py-3 font-medium">Old Name</th>
                    <th className="text-center px-2 py-3 font-medium"></th>
                    <th className="text-left px-4 py-3 font-medium">New Name</th>
                    <th className="text-left px-4 py-3 font-medium">Alliance</th>
                    <th className="text-left px-4 py-3 font-medium">Detected</th>
                  </tr>
                </thead>
                <tbody>
                  {nameChanges.map((nc, idx) => (
                    <tr key={`${nc.governor_id}-${idx}`} className="border-b border-border hover:bg-border/50">
                      <td className="px-4 py-3 font-mono text-muted text-xs">{nc.governor_id}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-1 bg-red-500/20 text-red-400 rounded text-xs line-through">
                          {nc.old_name}
                        </span>
                      </td>
                      <td className="px-2 py-3 text-center text-yellow-400">→</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-1 bg-green-500/20 text-green-400 rounded text-xs font-medium">
                          {nc.new_name}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-1 bg-accent/20 text-accent rounded text-xs">
                          {nc.current_alliance || "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted text-xs">
                        {new Date(nc.changed_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : activeTab === 'bans' ? (
      /* Bans List Tab */
        <div className="card">
          <h3 className="font-bold mb-4">Active Title Bans</h3>
          {bans.length === 0 ? (
            <p className="text-muted py-8 text-center">No active bans</p>
          ) : (
            <div className="space-y-2">
              {bans.map(ban => (
                <div key={ban.id} className="flex items-center justify-between p-3 bg-bg rounded-lg border border-red-500/30">
                  <div>
                    <span className="font-medium">{ban.governor_name}</span>
                    <span className="text-muted ml-2">(ID: {ban.governor_id})</span>
                    {ban.reason && (
                      <p className="text-sm text-muted mt-1">Reason: {ban.reason}</p>
                    )}
                    <p className="text-xs text-muted">
                      Banned: {new Date(ban.created_at).toLocaleDateString()}
                      {ban.expires_at && ` • Expires: ${new Date(ban.expires_at).toLocaleDateString()}`}
                    </p>
                  </div>
                  <button
                    onClick={() => handleUnban(ban.id)}
                    className="px-3 py-1 bg-green-500 text-white rounded hover:bg-green-600"
                  >
                    ✓ Unban
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : activeTab === 'players' ? (
        <>
          {/* Filters */}
      <div className="card">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm text-muted mb-1">Search Player</label>
            <input
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder="Player name..."
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Alliance</label>
            <input
              type="text"
              value={alliance}
              onChange={(e) => { setAlliance(e.target.value); setPage(1); }}
              placeholder="Alliance tag..."
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Sort By</label>
            <select
              value={sortBy}
              onChange={(e) => { setSortBy(e.target.value); setPage(1); }}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            >
              <option value="power">Power</option>
              <option value="kill_points">Kill Points</option>
              <option value="t4_kills">T4 Kills</option>
              <option value="t5_kills">T5 Kills</option>
              <option value="dead">Dead</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Order</label>
            <select
              value={sortDir}
              onChange={(e) => { setSortDir(e.target.value); setPage(1); }}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            >
              <option value="desc">Highest First</option>
              <option value="asc">Lowest First</option>
            </select>
          </div>
        </div>
      </div>

      {/* Results info */}
      <p className="text-sm text-muted">
        Found {totalCount.toLocaleString()} players
      </p>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto -mx-4 sm:mx-0">
          <table className="w-full text-sm min-w-[900px]">
            <thead>
              <tr className="border-b border-border bg-bg">
                <th className="text-left px-3 py-3 font-medium">#</th>
                <th className="text-left px-3 py-3 font-medium">Name</th>
                <th className="text-left px-3 py-3 font-medium">Alliance</th>
                <th 
                  className="text-right px-3 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("power")}
                >
                  Power<SortIcon field="power" />
                </th>
                <th 
                  className="text-right px-3 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("kill_points")}
                >
                  KP<SortIcon field="kill_points" />
                </th>
                <th 
                  className="text-right px-3 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("t4_kills")}
                >
                  T4<SortIcon field="t4_kills" />
                </th>
                <th 
                  className="text-right px-3 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("t5_kills")}
                >
                  T5<SortIcon field="t5_kills" />
                </th>
                <th 
                  className="text-right px-3 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("dead")}
                >
                  Dead<SortIcon field="dead" />
                </th>
                <th className="text-center px-3 py-3 font-medium">Status</th>
                <th className="text-center px-3 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={10} className="text-center py-12 text-muted">
                    <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
                    Loading...
                  </td>
                </tr>
              ) : governors.length === 0 ? (
                <tr>
                  <td colSpan={10} className="text-center py-12 text-muted">
                    No players found
                  </td>
                </tr>
              ) : (
                governors.map((gov, idx) => (
                  <tr key={gov.governor_id} className={`border-b border-border hover:bg-border/50 ${gov.is_banned ? 'bg-red-500/10' : ''}`}>
                    <td className="px-3 py-3 text-muted">{(page - 1) * limit + idx + 1}</td>
                    <td className="px-3 py-3 font-medium">
                      {gov.name}
                      {gov.is_banned && <span className="ml-2 text-red-400">🚫</span>}
                    </td>
                    <td className="px-3 py-3">
                      <span className="px-2 py-1 bg-accent/20 text-accent rounded text-xs">
                        {gov.alliance || "—"}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-sm">{formatNumber(gov.power)}</td>
                    <td className="px-3 py-3 text-right font-mono text-sm">{formatNumber(gov.kill_points)}</td>
                    <td className="px-3 py-3 text-right font-mono text-sm">{formatNumber(gov.t4_kills)}</td>
                    <td className="px-3 py-3 text-right font-mono text-sm">{formatNumber(gov.t5_kills)}</td>
                    <td className="px-3 py-3 text-right font-mono text-sm">{formatNumber(gov.dead)}</td>
                    <td className="px-3 py-3 text-center">
                      {gov.is_banned ? (
                        <span className="px-2 py-1 bg-red-500/20 text-red-400 rounded text-xs" title={gov.ban_reason || ''}>
                          Banned
                        </span>
                      ) : (
                        <span className="px-2 py-1 bg-green-500/20 text-green-400 rounded text-xs">
                          Active
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-center">
                      {gov.is_banned ? (
                        <button
                          onClick={() => handleUnbanByGovernor(gov.governor_id)}
                          className="px-2 py-1 bg-green-500 text-white rounded text-xs hover:bg-green-600"
                        >
                          Unban
                        </button>
                      ) : (
                        <button
                          onClick={() => { setSelectedPlayer(gov); setShowBanModal(true); }}
                          className="px-2 py-1 bg-red-500 text-white rounded text-xs hover:bg-red-600"
                        >
                          Ban
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-border">
            <p className="text-sm text-muted">
              Page {page} of {totalPages}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page === 1}
                className="px-3 py-1 rounded bg-bg border border-border disabled:opacity-50 hover:border-accent"
              >
                Prev
              </button>
              <button
                onClick={() => setPage(Math.min(totalPages, page + 1))}
                disabled={page === totalPages}
                className="px-3 py-1 rounded bg-bg border border-border disabled:opacity-50 hover:border-accent"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
      </>
      ) : null}
    </div>
  );
}
