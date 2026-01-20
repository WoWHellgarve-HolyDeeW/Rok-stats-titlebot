"use client";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/lib/auth";

interface Scan { id: number; scanned_at: string; }
interface PowerTier { min_power: number; max_power: number; kills_goal: number; dead_goal: number; power_coeff: number; dkp_goal?: number; }
interface DKPWeights { dkp_enabled: boolean; weight_t4: number; weight_t5: number; weight_dead: number; use_power_penalty: boolean; dkp_goal?: number; power_tiers?: PowerTier[] | null; }
interface SummaryStats { totalPlayers: number; totalT4Kills: number; totalT5Kills: number; totalKillPoints: number; totalDeaths: number; totalPower: number; }
interface PlayerData { governor_id: number; name: string; alliance: string | null; power: number; power_gain: number; kill_points_gain: number; t4_kills_gain: number; t5_kills_gain: number; dead_gain: number; dkp_score: number; }

// Default power tiers from KvK 7 spreadsheet (KD 3167)
// Format: power range → kills_goal (T4+T5), dead_goal, power_coeff
const DEFAULT_POWER_TIERS: PowerTier[] = [
  { min_power: 0, max_power: 5000001, kills_goal: 0, dead_goal: 0, power_coeff: 0.19 },           // Below 5M - no requirements
  { min_power: 5000001, max_power: 10000001, kills_goal: 288750, dead_goal: 45000, power_coeff: 0.19 },
  { min_power: 10000001, max_power: 15000001, kills_goal: 652500, dead_goal: 93750, power_coeff: 0.19 },
  { min_power: 15000001, max_power: 25000001, kills_goal: 866250, dead_goal: 135000, power_coeff: 0.19 },
  { min_power: 25000001, max_power: 35000001, kills_goal: 1631250, dead_goal: 234375, power_coeff: 0.19 },
  { min_power: 35000001, max_power: 40000001, kills_goal: 2756250, dead_goal: 262500, power_coeff: 0.19 },
  { min_power: 40000001, max_power: 45000001, kills_goal: 3900000, dead_goal: 330000, power_coeff: 0.19 },
  { min_power: 45000001, max_power: 50000001, kills_goal: 5062500, dead_goal: 472500, power_coeff: 0.30 },
  { min_power: 50000001, max_power: 55000001, kills_goal: 5812500, dead_goal: 562500, power_coeff: 0.30 },
  { min_power: 55000001, max_power: 60000001, kills_goal: 6393750, dead_goal: 660000, power_coeff: 0.30 },
  { min_power: 60000001, max_power: 65000001, kills_goal: 7200000, dead_goal: 765000, power_coeff: 0.30 },
  { min_power: 65000001, max_power: 70000001, kills_goal: 8287500, dead_goal: 926250, power_coeff: 0.30 },
  { min_power: 70000001, max_power: 75000001, kills_goal: 9450000, dead_goal: 1050000, power_coeff: 0.30 },
  { min_power: 75000001, max_power: 80000001, kills_goal: 10687500, dead_goal: 1125000, power_coeff: 0.30 },
  { min_power: 80000001, max_power: 85000001, kills_goal: 12000000, dead_goal: 1380000, power_coeff: 0.30 },
  { min_power: 85000001, max_power: 90000001, kills_goal: 14025000, dead_goal: 1785000, power_coeff: 0.30 },
  { min_power: 90000001, max_power: 100000001, kills_goal: 16875000, dead_goal: 2160000, power_coeff: 0.38 },
  { min_power: 100000001, max_power: 125000001, kills_goal: 22500000, dead_goal: 2625000, power_coeff: 0.38 },
  { min_power: 125000001, max_power: 999999999, kills_goal: 32812000, dead_goal: 3750000, power_coeff: 0.38 },
];

export default function KDDashboardPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const kingdom = params.kingdom as string;
  const { token, kingdom: authKingdom, isAuthenticated, isOwner } = useAuth();
  const canEdit = isAuthenticated && isOwner && authKingdom === parseInt(kingdom);
  const [loading, setLoading] = useState(true);
  const [players, setPlayers] = useState<PlayerData[]>([]);
  const [scans, setScans] = useState<Scan[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [summaryStats, setSummaryStats] = useState<SummaryStats | null>(null);
  const [dkpWeights, setDkpWeights] = useState<DKPWeights>({ dkp_enabled: true, weight_t4: 2, weight_t5: 4, weight_dead: 6, use_power_penalty: true, dkp_goal: 0, power_tiers: null });
  const [showFormulaModal, setShowFormulaModal] = useState(false);
  const [search, setSearch] = useState(searchParams.get("search") || "");
  const [alliance, setAlliance] = useState(searchParams.get("alliance") || "");
  const [sortBy, setSortBy] = useState("dkp_score");
  const [sortDir, setSortDir] = useState("desc");
  const [page, setPage] = useState(1);
  const [startScan, setStartScan] = useState("");
  const [endScan, setEndScan] = useState("");
  const limit = 25;
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  useEffect(() => {
    const fetchScans = async () => {
      try {
        const res = await fetch(apiBase + "/kingdoms/" + kdNum + "/scans");
        if (res.ok) {
          const data = await res.json();
          setScans(data);
          if (data.length >= 2 && !startScan && !endScan) {
            setStartScan(data[data.length - 1].id.toString());
            setEndScan(data[0].id.toString());
          } else if (data.length === 1) {
            setStartScan(data[0].id.toString());
            setEndScan(data[0].id.toString());
          }
        }
      } catch (err) { console.error("Failed to fetch scans:", err); }
    };
    fetchScans();
  }, [apiBase, kdNum]);

  useEffect(() => {
    const fetchDKPWeights = async () => {
      try {
        const res = await fetch(apiBase + "/kingdoms/" + kdNum + "/dkp-rule");
        if (res.ok) {
          const data = await res.json();
          if (data) setDkpWeights({ dkp_enabled: data.dkp_enabled ?? true, weight_t4: data.weight_t4 ?? 2, weight_t5: data.weight_t5 ?? 4, weight_dead: data.weight_dead ?? 6, use_power_penalty: data.use_power_penalty ?? true, dkp_goal: data.dkp_goal || 0, power_tiers: data.power_tiers || null });
        }
      } catch (err) { console.log("Using default DKP weights"); }
    };
    fetchDKPWeights();
  }, [apiBase, kdNum]);

  const fetchData = useCallback(async () => {
    if (!startScan || !endScan) return;
    setLoading(true);
    try {
      // For DKP sorting, we need to fetch all and sort locally (since DKP weights are customizable)
      // For other fields, let the backend handle sorting with pagination
      const isDkpSort = sortBy === "dkp_score";
      const backendSortBy = isDkpSort ? "dead_gain" : sortBy; // Use dead_gain as proxy for DKP
      
      const p = new URLSearchParams({ 
        from_scan: startScan, 
        to_scan: endScan, 
        skip: isDkpSort ? "0" : ((page - 1) * limit).toString(), 
        limit: isDkpSort ? "10000" : limit.toString(), 
        sort_by: backendSortBy, 
        sort_dir: sortDir 
      });
      if (search) p.set("search", search);
      if (alliance) p.set("alliance", alliance);
      const res = await fetch(apiBase + "/kingdoms/" + kdNum + "/gains?" + p);
      if (res.ok) {
        const data = await res.json();
        const items = data.items || [];
        
        // Calculate DKP for all items using formula: (T4 × weight_t4) + (T5 × weight_t5) + (Dead × weight_dead) - (Power × power_coeff)
        const playersWithDKP = items.map((x: any) => {
          const t4Part = (x.t4_kills_gain || 0) * dkpWeights.weight_t4;
          const t5Part = (x.t5_kills_gain || 0) * dkpWeights.weight_t5;
          const deadPart = (x.dead_gain || 0) * dkpWeights.weight_dead;
          let powerPenalty = 0;
          const playerPower = x.power || 0;
          
          // Apply power penalty if enabled
          if (dkpWeights.use_power_penalty) {
            // Try to find tier-specific coefficient
            if (dkpWeights.power_tiers && dkpWeights.power_tiers.length > 0) {
              const tier = dkpWeights.power_tiers.find(t => playerPower >= t.min_power && playerPower < t.max_power);
              if (tier && tier.power_coeff > 0) {
                powerPenalty = playerPower * tier.power_coeff;
              }
            }
            // Fallback: use default coefficients based on power
            if (powerPenalty === 0 && playerPower > 0) {
              let defaultCoeff = 0.19; // Default for low power
              if (playerPower >= 90000000) defaultCoeff = 0.38;
              else if (playerPower >= 45000000) defaultCoeff = 0.30;
              powerPenalty = playerPower * defaultCoeff;
            }
          }
          
          const dkpScore = Math.round(t4Part + t5Part + deadPart - powerPenalty);
          return { ...x, power: playerPower, dkp_score: Math.max(0, dkpScore) }; // Don't allow negative DKP
        });
        
        if (isDkpSort) {
          // Sort by DKP locally and paginate
          playersWithDKP.sort((a: PlayerData, b: PlayerData) => sortDir === "desc" ? b.dkp_score - a.dkp_score : a.dkp_score - b.dkp_score);
          const startIdx = (page - 1) * limit;
          setPlayers(playersWithDKP.slice(startIdx, startIdx + limit));
          setTotalCount(playersWithDKP.length);
        } else {
          // Backend already sorted and paginated
          setPlayers(playersWithDKP);
          setTotalCount(data.total || 0);
        }
        
        // Summary stats (fetch all for totals)
        const summary: SummaryStats = { totalPlayers: data.total || playersWithDKP.length, totalT4Kills: 0, totalT5Kills: 0, totalKillPoints: 0, totalDeaths: 0, totalPower: 0 };
        if (!isDkpSort) {
          const allRes = await fetch(apiBase + "/kingdoms/" + kdNum + "/gains?from_scan=" + startScan + "&to_scan=" + endScan + "&skip=0&limit=10000");
          if (allRes.ok) {
            const allData = await allRes.json();
            (allData.items || []).forEach((x: any) => { summary.totalT4Kills += x.t4_kills_gain || 0; summary.totalT5Kills += x.t5_kills_gain || 0; summary.totalKillPoints += x.kill_points_gain || 0; summary.totalDeaths += x.dead_gain || 0; summary.totalPower += x.power_gain || 0; });
          }
        } else {
          playersWithDKP.forEach((x: any) => { summary.totalT4Kills += x.t4_kills_gain || 0; summary.totalT5Kills += x.t5_kills_gain || 0; summary.totalKillPoints += x.kill_points_gain || 0; summary.totalDeaths += x.dead_gain || 0; summary.totalPower += x.power_gain || 0; });
        }
        setSummaryStats(summary);
      }
    } catch (err) { console.error("Failed to fetch data:", err); } finally { setLoading(false); }
  }, [page, sortBy, sortDir, search, alliance, startScan, endScan, apiBase, kdNum, dkpWeights, limit]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const formatNumber = (n: number | null | undefined) => { if (n == null) return "0"; if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + "B"; if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + "M"; if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "K"; return n.toLocaleString(); };
  const handleSort = (field: string) => { if (sortBy === field) setSortDir(sortDir === "asc" ? "desc" : "asc"); else { setSortBy(field); setSortDir("desc"); } setPage(1); };
  const SortIcon = ({ field }: { field: string }) => <span className="ml-1 text-xs">{sortBy === field ? (sortDir === "asc" ? "↑" : "↓") : ""}</span>;
  const totalPages = Math.ceil(totalCount / limit);
  const getDkpProgress = (score: number, playerPower: number, t4Kills: number, t5Kills: number, dead: number) => { 
    // Use configured tiers or fallback to default template
    const tiers = (dkpWeights.power_tiers && dkpWeights.power_tiers.length > 0) 
      ? dkpWeights.power_tiers 
      : DEFAULT_POWER_TIERS;
    
    const tier = tiers.find(t => playerPower >= t.min_power && playerPower < t.max_power);
    if (tier) {
      const killsTotal = t4Kills + t5Kills;
      const killsGoal = tier.kills_goal || 0;
      const deadGoal = tier.dead_goal || 0;
      
      // If both goals are set, average them
      if (killsGoal > 0 && deadGoal > 0) {
        const killsProgress = Math.min(100, (killsTotal / killsGoal) * 100);
        const deadProgress = Math.min(100, (dead / deadGoal) * 100);
        return Math.round((killsProgress + deadProgress) / 2);
      } else if (killsGoal > 0) {
        return Math.min(100, Math.round((killsTotal / killsGoal) * 100));
      } else if (deadGoal > 0) {
        return Math.min(100, Math.round((dead / deadGoal) * 100));
      }
      
      // Legacy: use dkp_goal if no specific goals
      if (tier.dkp_goal && tier.dkp_goal > 0) {
        return Math.min(100, Math.round((score / tier.dkp_goal) * 100));
      }
    }
    
    // No tier found or no goals - don't show progress bar
    return null;
  };
  const handleExportExcel = () => { const headers = ["Rank", "Name", "Alliance", "DKP Score", "Power", "Power Gain", "T4 Kills", "T5 Kills", "Deaths", "KP Gain"]; const rows = players.map((p, idx) => [(page - 1) * limit + idx + 1, p.name, p.alliance || "", p.dkp_score, p.power, p.power_gain, p.t4_kills_gain, p.t5_kills_gain, p.dead_gain, p.kill_points_gain]); const csvContent = [headers.join(","), ...rows.map(r => r.join(","))].join("\n"); const blob = new Blob([csvContent], { type: "text/csv" }); const url = window.URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "kd" + kdNum + "_rankings.csv"; a.click(); window.URL.revokeObjectURL(url); };

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div><h1 className="text-3xl font-bold text-accent">KD {kingdom} Dashboard</h1><p className="text-muted">Player rankings and statistics</p></div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2"><label className="text-sm text-muted">Start:</label><select value={startScan} onChange={(e) => { setStartScan(e.target.value); setPage(1); }} className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent min-w-[180px]">{scans.slice().reverse().map((s) => <option key={s.id} value={s.id}>{new Date(s.scanned_at).toLocaleDateString()} {new Date(s.scanned_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</option>)}</select></div>
          <div className="flex items-center gap-2"><label className="text-sm text-muted">End:</label><select value={endScan} onChange={(e) => { setEndScan(e.target.value); setPage(1); }} className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent min-w-[180px]">{scans.map((s) => <option key={s.id} value={s.id}>{new Date(s.scanned_at).toLocaleDateString()} {new Date(s.scanned_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</option>)}</select></div>
          <button onClick={handleExportExcel} className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>Export</button>
        </div>
      </div>
      {/* DKP Formula Card - Only show if DKP is enabled */}
      {dkpWeights.dkp_enabled ? (
        <div className="card bg-gradient-to-r from-purple-900/30 to-pink-900/30 border-purple-500/30">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-sm font-medium text-purple-300">DKP FORMULA</h3>
                <span className={`text-xs px-2 py-0.5 rounded ${dkpWeights.use_power_penalty ? 'bg-purple-600 text-white' : 'bg-gray-600 text-gray-300'}`}>
                  Power Penalty {dkpWeights.use_power_penalty ? 'ON' : 'OFF'}
                </span>
              </div>
              <p className="text-base sm:text-xl font-mono flex flex-wrap items-center gap-1">
                <span className="text-blue-400">T4</span><span className="text-muted">×</span><span className="text-white">{dkpWeights.weight_t4}</span>
                <span className="text-muted mx-1">+</span>
                <span className="text-orange-400">T5</span><span className="text-muted">×</span><span className="text-white">{dkpWeights.weight_t5}</span>
                <span className="text-muted mx-1">+</span>
                <span className="text-red-400">DEAD</span><span className="text-muted">×</span><span className="text-white">{dkpWeights.weight_dead}</span>
                {dkpWeights.use_power_penalty && <><span className="text-muted mx-1">−</span><span className="text-purple-400">PWR×coeff</span></>}
              </p>
              {dkpWeights.use_power_penalty && <p className="text-xs text-muted mt-1">Coeff: &lt;45M=0.19 | 45-90M=0.30 | &gt;90M=0.38</p>}
            </div>
            {canEdit && <button onClick={() => setShowFormulaModal(true)} className="bg-purple-600/50 hover:bg-purple-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap">Edit Formula</button>}
          </div>
        </div>
      ) : canEdit ? (
        <div className="card bg-gradient-to-r from-gray-800/50 to-gray-700/30 border-gray-600/30">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium text-gray-400">DKP TRACKING DISABLED</h3>
              <p className="text-xs text-muted">Enable DKP tracking to show scores and rankings during KvK</p>
            </div>
            <button onClick={() => setShowFormulaModal(true)} className="bg-gray-600/50 hover:bg-gray-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap">Enable DKP</button>
          </div>
        </div>
      ) : null}
      {summaryStats && <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <div className="card bg-gradient-to-br from-blue-900/50 to-blue-800/30 border-blue-500/30"><p className="text-xs text-blue-300 uppercase tracking-wider mb-1">Players</p><p className="text-2xl font-bold text-white">{summaryStats.totalPlayers.toLocaleString()}</p></div>
        <div className="card bg-gradient-to-br from-cyan-900/50 to-cyan-800/30 border-cyan-500/30"><p className="text-xs text-cyan-300 uppercase tracking-wider mb-1">T4 Kills</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalT4Kills)}</p></div>
        <div className="card bg-gradient-to-br from-orange-900/50 to-orange-800/30 border-orange-500/30"><p className="text-xs text-orange-300 uppercase tracking-wider mb-1">T5 Kills</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalT5Kills)}</p></div>
        <div className="card bg-gradient-to-br from-green-900/50 to-green-800/30 border-green-500/30"><p className="text-xs text-green-300 uppercase tracking-wider mb-1">Total KP</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalKillPoints)}</p></div>
        <div className="card bg-gradient-to-br from-red-900/50 to-red-800/30 border-red-500/30"><p className="text-xs text-red-300 uppercase tracking-wider mb-1">Deaths</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalDeaths)}</p></div>
        <div className="card bg-gradient-to-br from-purple-900/50 to-purple-800/30 border-purple-500/30"><p className="text-xs text-purple-300 uppercase tracking-wider mb-1">Power Gain</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalPower)}</p></div>
      </div>}
      <div className="card"><div className="flex flex-col sm:flex-row gap-4"><div className="flex-1"><input type="text" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search by name or governor ID..." className="w-full bg-bg border border-border rounded-lg px-4 py-2.5 focus:outline-none focus:border-accent"/></div><div className="sm:w-48"><input type="text" value={alliance} onChange={(e) => { setAlliance(e.target.value); setPage(1); }} placeholder="Alliance..." className="w-full bg-bg border border-border rounded-lg px-4 py-2.5 focus:outline-none focus:border-accent"/></div></div></div>
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto -mx-4 sm:mx-0">
          <table className="w-full text-sm min-w-[800px]">
            <thead><tr className="border-b border-border bg-bg/80"><th className="text-left px-4 py-3 font-semibold text-muted">#</th><th className="text-left px-4 py-3 font-semibold">PLAYER</th>{dkpWeights.dkp_enabled && <th className="text-right px-4 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("dkp_score")}><span className="text-yellow-400">DKP</span><SortIcon field="dkp_score" /></th>}<th className="text-right px-4 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("power")}>POWER<SortIcon field="power" /></th><th className="text-right px-4 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("dead_gain")}><span className="text-red-400">DEADS</span><SortIcon field="dead_gain" /></th><th className="text-right px-4 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("t4_kills_gain")}><span className="text-blue-400">T4</span><SortIcon field="t4_kills_gain" /></th><th className="text-right px-4 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("t5_kills_gain")}><span className="text-orange-400">T5</span><SortIcon field="t5_kills_gain" /></th><th className="text-right px-4 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("kill_points_gain")}>KP<SortIcon field="kill_points_gain" /></th></tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={dkpWeights.dkp_enabled ? 8 : 7} className="text-center py-16 text-muted"><div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-accent mx-auto mb-3"></div>Loading...</td></tr> : players.length === 0 ? <tr><td colSpan={dkpWeights.dkp_enabled ? 8 : 7} className="text-center py-16 text-muted">No data found</td></tr> : players.map((player, idx) => {
                const rank = (page - 1) * limit + idx + 1;
                const dkpProgress = dkpWeights.dkp_enabled ? getDkpProgress(player.dkp_score, player.power, player.t4_kills_gain, player.t5_kills_gain, player.dead_gain) : null;
                return <tr key={player.governor_id} className="border-b border-border/50 hover:bg-border/30 transition-colors">
                  <td className="px-4 py-3 text-muted font-mono">{rank}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center text-white font-bold text-sm">{player.name.substring(0, 2).toUpperCase()}</div>
                      <div>
                        <div className="text-xs text-muted">#{player.governor_id}</div>
                        <div className="font-medium">{player.name}</div>
                        {player.alliance && <span className="inline-block mt-1 px-2 py-0.5 bg-cyan-600/30 text-cyan-400 rounded text-xs font-medium">{player.alliance}</span>}
                      </div>
                    </div>
                  </td>
                  {dkpWeights.dkp_enabled && <td className="px-4 py-3">
                    <div className="text-right">
                      <div className="font-bold text-white mb-1">{formatNumber(player.dkp_score)}</div>
                      {dkpProgress !== null && (
                        <div className="w-24 ml-auto">
                          <div className="h-5 bg-gray-700 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full flex items-center justify-center text-xs font-bold text-white ${dkpProgress >= 100 ? 'bg-green-500' : dkpProgress >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`} style={{ width: `${Math.max(dkpProgress, 15)}%` }}>{dkpProgress}%</div>
                          </div>
                        </div>
                      )}
                    </div>
                  </td>}
                  <td className="px-4 py-3 text-right">
                    <div className="font-mono">{formatNumber(player.power)}</div>
                    <div className={`text-xs ${player.power_gain >= 0 ? 'text-green-400' : 'text-red-400'}`}>({player.power_gain >= 0 ? '+' : ''}{formatNumber(player.power_gain)})</div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-white">{formatNumber(player.dead_gain)}</td>
                  <td className="px-4 py-3 text-right font-mono text-white">{formatNumber(player.t4_kills_gain)}</td>
                  <td className="px-4 py-3 text-right font-mono text-white">{formatNumber(player.t5_kills_gain)}</td>
                  <td className="px-4 py-3 text-right font-mono text-white">{formatNumber(player.kill_points_gain)}</td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && <div className="flex flex-col sm:flex-row items-center justify-between px-4 py-3 border-t border-border gap-4"><p className="text-sm text-muted">Showing {(page - 1) * limit + 1} to {Math.min(page * limit, totalCount)} of {totalCount.toLocaleString()}</p><div className="flex items-center gap-2"><button onClick={() => setPage(1)} disabled={page === 1} className="px-3 py-1.5 rounded bg-bg border border-border disabled:opacity-50 hover:border-accent">First</button><button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} className="px-3 py-1.5 rounded bg-bg border border-border disabled:opacity-50 hover:border-accent">Prev</button><span className="px-4 py-1.5 text-muted">{page}/{totalPages}</span><button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page === totalPages} className="px-3 py-1.5 rounded bg-bg border border-border disabled:opacity-50 hover:border-accent">Next</button><button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="px-3 py-1.5 rounded bg-bg border border-border disabled:opacity-50 hover:border-accent">Last</button></div></div>}
      </div>
      {showFormulaModal && <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4 overflow-y-auto"><div className="card max-w-2xl w-full my-8"><h3 className="text-xl font-bold mb-4">DKP Settings</h3><div className="space-y-6">
        
        {/* Master DKP Toggle */}
        <div className={`p-4 rounded-lg border-2 transition-colors ${dkpWeights.dkp_enabled ? 'bg-green-900/30 border-green-500/50' : 'bg-gray-800/30 border-gray-600/50'}`}>
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-white">🏆 DKP Tracking</h4>
                <span className={`text-xs px-2 py-0.5 rounded ${dkpWeights.dkp_enabled ? 'bg-green-600 text-white' : 'bg-gray-600 text-gray-300'}`}>
                  {dkpWeights.dkp_enabled ? 'ACTIVE' : 'DISABLED'}
                </span>
              </div>
              <p className="text-xs text-muted mt-1">
                {dkpWeights.dkp_enabled 
                  ? '✓ DKP scores are calculated and shown in rankings' 
                  : '○ DKP column is hidden - enable during KvK'}
              </p>
            </div>
            <button 
              onClick={() => setDkpWeights({ ...dkpWeights, dkp_enabled: !dkpWeights.dkp_enabled })} 
              className={`w-14 h-7 rounded-full transition-colors flex items-center ${dkpWeights.dkp_enabled ? 'bg-green-600' : 'bg-gray-600'}`}
            >
              <div className={`w-6 h-6 bg-white rounded-full shadow transition-transform ${dkpWeights.dkp_enabled ? 'translate-x-7' : 'translate-x-0.5'}`}></div>
            </button>
          </div>
        </div>

        {/* Only show formula settings if DKP is enabled */}
        {dkpWeights.dkp_enabled && <>
        {/* Points Section */}
        <div>
          <h4 className="text-sm font-semibold text-purple-300 uppercase tracking-wider mb-3">Point Values</h4>
          <div className="grid grid-cols-3 gap-3">
            <div><label className="block text-xs text-blue-400 mb-1">T4 Kills =</label><input type="number" step="0.5" value={dkpWeights.weight_t4} onChange={(e) => setDkpWeights({ ...dkpWeights, weight_t4: parseFloat(e.target.value) || 0 })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 text-center"/><span className="text-xs text-muted">pts/kill</span></div>
            <div><label className="block text-xs text-orange-400 mb-1">T5 Kills =</label><input type="number" step="0.5" value={dkpWeights.weight_t5} onChange={(e) => setDkpWeights({ ...dkpWeights, weight_t5: parseFloat(e.target.value) || 0 })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-orange-500 text-center"/><span className="text-xs text-muted">pts/kill</span></div>
            <div><label className="block text-xs text-red-400 mb-1">Deaths =</label><input type="number" step="0.5" value={dkpWeights.weight_dead} onChange={(e) => setDkpWeights({ ...dkpWeights, weight_dead: parseFloat(e.target.value) || 0 })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-red-500 text-center"/><span className="text-xs text-muted">pts/dead</span></div>
          </div>
        </div>
        
        {/* Power Penalty Toggle - IMPORTANT */}
        <div className={`p-4 rounded-lg border-2 transition-colors ${dkpWeights.use_power_penalty ? 'bg-purple-900/30 border-purple-500/50' : 'bg-gray-800/30 border-gray-600/50'}`}>
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-white">⚡ Power Penalty</h4>
                <span className={`text-xs px-2 py-0.5 rounded ${dkpWeights.use_power_penalty ? 'bg-green-600 text-white' : 'bg-gray-600 text-gray-300'}`}>
                  {dkpWeights.use_power_penalty ? 'ON' : 'OFF'}
                </span>
              </div>
              <p className="text-xs text-muted mt-1">
                {dkpWeights.use_power_penalty 
                  ? '✓ DKP = (T4×2 + T5×4 + Dead×6) − (Power × coeff)' 
                  : '○ DKP = T4×2 + T5×4 + Dead×6 (no penalty)'}
              </p>
              <p className="text-xs text-yellow-400/80 mt-1">
                💡 Higher power players need more kills/deads to have positive DKP when ON
              </p>
            </div>
            <button 
              onClick={() => setDkpWeights({ ...dkpWeights, use_power_penalty: !dkpWeights.use_power_penalty })} 
              className={`w-14 h-7 rounded-full transition-colors flex items-center ${dkpWeights.use_power_penalty ? 'bg-purple-600' : 'bg-gray-600'}`}
            >
              <div className={`w-6 h-6 bg-white rounded-full shadow transition-transform ${dkpWeights.use_power_penalty ? 'translate-x-7' : 'translate-x-0.5'}`}></div>
            </button>
          </div>
        </div>
        
        {/* Power Tiers Section */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-semibold text-purple-300 uppercase tracking-wider">Power Tiers (Goals & Coefficients)</h4>
            <div className="flex gap-2">
              <button onClick={() => setDkpWeights({ ...dkpWeights, power_tiers: [...DEFAULT_POWER_TIERS] })} className="text-xs bg-green-600/50 hover:bg-green-600 px-2 py-1 rounded transition-colors" title="Load KvK template tiers">📋 Load Template</button>
              <button onClick={() => {
                const newTiers = [...(dkpWeights.power_tiers || [])];
                const lastMax = newTiers.length > 0 ? newTiers[newTiers.length - 1].max_power : 0;
                newTiers.push({ min_power: lastMax, max_power: lastMax + 10000000, kills_goal: 0, dead_goal: 0, power_coeff: 0.19 });
                setDkpWeights({ ...dkpWeights, power_tiers: newTiers });
              }} className="text-xs bg-purple-600/50 hover:bg-purple-600 px-2 py-1 rounded transition-colors">+ Add Tier</button>
            </div>
          </div>
          
          {(!dkpWeights.power_tiers || dkpWeights.power_tiers.length === 0) ? (
            <div className="text-center py-4 text-muted text-sm border border-dashed border-border rounded-lg">
              <p className="mb-2">No power tiers defined.</p>
              <button onClick={() => setDkpWeights({ ...dkpWeights, power_tiers: [...DEFAULT_POWER_TIERS] })} className="text-xs bg-green-600/50 hover:bg-green-600 px-3 py-1.5 rounded transition-colors">📋 Load KvK Template (19 tiers)</button>
            </div>
          ) : (
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
              <div className="grid grid-cols-6 gap-2 text-xs text-muted px-2 sticky top-0 bg-card py-1">
                <span className="col-span-2 text-center">Power Range (M)</span>
                <span className="text-center">Kills Goal</span>
                <span className="text-center">Dead Goal</span>
                <span className="text-center">PWR Coeff</span>
                <span></span>
              </div>
              {dkpWeights.power_tiers.map((tier, idx) => (
                <div key={idx} className="grid grid-cols-6 gap-2 items-center p-2 bg-bg/50 rounded-lg border border-border/50">
                  <div className="col-span-2 flex items-center gap-2 justify-center">
                    <input type="number" value={Math.round(tier.min_power / 1000000)} onChange={(e) => {
                      const newTiers = [...dkpWeights.power_tiers!];
                      newTiers[idx] = { ...tier, min_power: (parseInt(e.target.value) || 0) * 1000000 };
                      setDkpWeights({ ...dkpWeights, power_tiers: newTiers });
                    }} style={{width: '70px'}} className="bg-bg border border-border rounded px-2 py-1.5 text-sm text-center"/>
                    <span className="text-sm text-muted">→</span>
                    <input type="number" value={Math.round(tier.max_power / 1000000)} onChange={(e) => {
                      const newTiers = [...dkpWeights.power_tiers!];
                      newTiers[idx] = { ...tier, max_power: (parseInt(e.target.value) || 0) * 1000000 };
                      setDkpWeights({ ...dkpWeights, power_tiers: newTiers });
                    }} style={{width: '70px'}} className="bg-bg border border-border rounded px-2 py-1.5 text-sm text-center"/>
                    <span className="text-sm text-muted font-semibold">M</span>
                  </div>
                  <input type="text" value={(tier.kills_goal || 0).toLocaleString()} onChange={(e) => {
                    const newTiers = [...dkpWeights.power_tiers!];
                    newTiers[idx] = { ...tier, kills_goal: parseInt(e.target.value.replace(/[^\d]/g, '')) || 0 };
                    setDkpWeights({ ...dkpWeights, power_tiers: newTiers });
                  }} placeholder="0" className="w-full bg-bg border border-border rounded px-1 py-1.5 text-xs text-center" title="Kills goal (T4+T5)"/>
                  <input type="text" value={(tier.dead_goal || 0).toLocaleString()} onChange={(e) => {
                    const newTiers = [...dkpWeights.power_tiers!];
                    newTiers[idx] = { ...tier, dead_goal: parseInt(e.target.value.replace(/[^\d]/g, '')) || 0 };
                    setDkpWeights({ ...dkpWeights, power_tiers: newTiers });
                  }} placeholder="0" className="w-full bg-bg border border-border rounded px-1 py-1.5 text-xs text-center" title="Dead goal"/>
                  <input type="number" value={tier.power_coeff || 0} step="0.01" onChange={(e) => {
                    const newTiers = [...dkpWeights.power_tiers!];
                    newTiers[idx] = { ...tier, power_coeff: parseFloat(e.target.value) || 0 };
                    setDkpWeights({ ...dkpWeights, power_tiers: newTiers });
                  }} placeholder="0.19" className="w-full bg-bg border border-border rounded px-1 py-1.5 text-xs text-center" title="Power coefficient"/>
                  <button onClick={() => {
                    const newTiers = dkpWeights.power_tiers!.filter((_, i) => i !== idx);
                    setDkpWeights({ ...dkpWeights, power_tiers: newTiers.length > 0 ? newTiers : null });
                  }} className="text-red-400 hover:text-red-300 justify-self-center"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg></button>
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-muted mt-2">Power coeff: 0.19 (&lt;45M), 0.30 (45-90M), 0.38 (&gt;90M). Kills = T4+T5 combined.</p>
        </div>
        </>}
        
        <div className="flex gap-3 pt-4"><button onClick={() => setShowFormulaModal(false)} className="flex-1 px-4 py-2 rounded-lg border border-border hover:bg-border transition-colors">Cancel</button><button onClick={async () => { try { const headers: Record<string, string> = { "Content-Type": "application/json" }; if (token) headers["Authorization"] = `Bearer ${token}`; await fetch(apiBase + "/kingdoms/" + kdNum + "/dkp-rule", { method: "POST", headers, body: JSON.stringify(dkpWeights) }); setShowFormulaModal(false); fetchData(); } catch (err) { console.error("Failed to save formula:", err); } }} className="flex-1 px-4 py-2 rounded-lg bg-accent text-bg font-medium hover:bg-accent/80 transition-colors">Save</button></div>
      </div></div></div>}
    </div>
  );
}