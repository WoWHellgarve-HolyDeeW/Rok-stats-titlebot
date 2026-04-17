"use client";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import PlayerAvatar from "@/components/PlayerAvatar";

interface Scan { id: number; scanned_at: string; scan_type?: string | null; source_file?: string | null; record_count?: number | null; batch_count?: number | null; session_started_at?: string | null; session_ended_at?: string | null; }
interface PowerTier { min_power: number; max_power: number; kills_goal: number; dead_goal: number; power_coeff: number; dkp_goal?: number; }
interface DKPWeights { dkp_enabled: boolean; weight_t4: number; weight_t5: number; weight_dead: number; use_power_penalty: boolean; dkp_goal?: number; power_tiers?: PowerTier[] | null; }
interface SummaryStats { totalPlayers: number; totalT4Kills: number; totalT5Kills: number; totalKillPoints: number; totalDeaths: number; totalPower: number; totalAcclaimsGain: number; }
interface PlayerData { governor_id: number; name: string; avatar_url?: string | null; alliance: string | null; power: number; highest_power: number; acclaims: number; highest_acclaims?: number; power_gain: number; kill_points_gain: number; acclaims_gain: number; t1_kills_gain: number; t2_kills_gain: number; t3_kills_gain: number; t4_kills_gain: number; t5_kills_gain: number; t4_kp_gain: number; t5_kp_gain: number; dead_gain: number; dkp_score: number; }
interface WarPeriod { index: number; label: string; start: string | null; end: string | null; configured: boolean; }
interface KvKSettings { kvk_active: string | null; kvk_start: string | null; kvk_end: string | null; war_periods: WarPeriod[]; }

const getScanComparisonGroup = (scan?: Scan | null) => {
  if (!scan) return "";
  const scanType = (scan.scan_type || "").toLowerCase();
  const sourceFile = (scan.source_file || "").toLowerCase();
  if (scanType === "bot_scan" || sourceFile.startsWith("bot_scan_")) return "profile_scan";
  if (scanType.startsWith("clean_") || sourceFile.startsWith("clean_scan::")) return "profile_scan";
  if (scanType === "kingdom" || sourceFile.endsWith(".csv")) return "kingdom_csv";
  return scanType || "other";
};

const getScanSourceLabel = (scan?: Scan | null) => {
  const scanType = (scan?.scan_type || "").toLowerCase();
  const sourceFile = (scan?.source_file || "").toLowerCase();
  if (scanType === "bot_scan" || sourceFile.startsWith("bot_scan_")) {
    return "Live Bot";
  }
  if (scanType.startsWith("clean_") || sourceFile.startsWith("clean_scan::")) {
    return "Clean Import";
  }
  switch (getScanComparisonGroup(scan)) {
    case "kingdom_csv":
      return "CSV Import";
    default:
      return scan?.scan_type || "Other";
  }
};

const getComparableWindowLabel = (start?: Scan | null, end?: Scan | null) => {
  if (!start || !end) return null;
  const startLabel = getScanSourceLabel(start);
  const endLabel = getScanSourceLabel(end);
  return startLabel === endLabel ? endLabel : `${startLabel} -> ${endLabel}`;
};

const findPreferredScanPair = (scans: Scan[]) => {
  const chronological = [...scans].sort((a, b) => new Date(a.scanned_at).getTime() - new Date(b.scanned_at).getTime());
  for (let endIndex = chronological.length - 1; endIndex > 0; endIndex -= 1) {
    for (let startIndex = endIndex - 1; startIndex >= 0; startIndex -= 1) {
      if (getScanComparisonGroup(chronological[startIndex]) === getScanComparisonGroup(chronological[endIndex])) {
        return { start: chronological[startIndex], end: chronological[endIndex] };
      }
    }
  }
  return null;
};

const formatScanOptionLabel = (scan: Scan) => {
  const scannedAt = new Date(scan.scanned_at);
  const recordCountLabel = scan.record_count ? ` · ${scan.record_count} players` : "";
  const batchCountLabel = scan.batch_count && scan.batch_count > 1 ? ` · ${scan.batch_count} batches` : "";
  return `${scannedAt.toLocaleDateString()} ${scannedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${getScanSourceLabel(scan)}${recordCountLabel}${batchCountLabel}`;
};

// Default power tiers from KvK 7 spreadsheet (KD 0000)
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
  const [kvkSettings, setKvkSettings] = useState<KvKSettings | null>(null);
  const [periodSelection, setPeriodSelection] = useState("scan_range");
  const [search, setSearch] = useState(searchParams.get("search") || "");
  const [alliance, setAlliance] = useState(searchParams.get("alliance") || "");
  const [allianceList, setAllianceList] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState("dkp_score");
  const [sortDir, setSortDir] = useState("desc");
  const [page, setPage] = useState(1);
  const [startScan, setStartScan] = useState("");
  const [endScan, setEndScan] = useState("");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [selectionWarning, setSelectionWarning] = useState<string | null>(null);
  const limit = 25;
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);
  const configuredWarPeriods = (kvkSettings?.war_periods || []).filter((period) => period.configured);
  const usingCustomDates = periodSelection === "custom_dates";
  const usingWarPeriods = periodSelection.startsWith("war_") && configuredWarPeriods.length > 0;
  const usingManualScans = periodSelection === "scan_range";
  const selectedWarIndex = periodSelection.startsWith("war_") ? parseInt(periodSelection.slice(4), 10) : null;
  const selectedWarLabel = periodSelection === "war_all"
    ? "All Configured Wars"
    : configuredWarPeriods.find((period) => period.index === selectedWarIndex)?.label || null;
  const selectedStartScan = scans.find((scan) => scan.id.toString() === startScan) || null;
  const selectedEndScan = scans.find((scan) => scan.id.toString() === endScan) || null;
  const selectedScanSourceLabel = usingManualScans && selectedStartScan && selectedEndScan && getScanComparisonGroup(selectedStartScan) === getScanComparisonGroup(selectedEndScan)
    ? getComparableWindowLabel(selectedStartScan, selectedEndScan)
    : null;

  const formatDateTimeInput = (value: string | null | undefined) => {
    if (!value) return "";
    return value.slice(0, 16);
  };

  useEffect(() => {
    const fetchScans = async () => {
      try {
        const res = await fetch(apiBase + "/kingdoms/" + kdNum + "/scans");
        if (res.ok) {
          const data = await res.json();
          setScans(data);
          if (data.length >= 2 && !startScan && !endScan) {
            const preferredPair = findPreferredScanPair(data);
            if (preferredPair) {
              setStartScan(preferredPair.start.id.toString());
              setEndScan(preferredPair.end.id.toString());
              setCustomStartDate(formatDateTimeInput(preferredPair.start.scanned_at));
              setCustomEndDate(formatDateTimeInput(preferredPair.end.scanned_at));
            } else {
              setStartScan(data[data.length - 1].id.toString());
              setEndScan(data[0].id.toString());
              setCustomStartDate(formatDateTimeInput(data[data.length - 1].scanned_at));
              setCustomEndDate(formatDateTimeInput(data[0].scanned_at));
            }
          } else if (data.length === 1) {
            setStartScan(data[0].id.toString());
            setEndScan(data[0].id.toString());
            setCustomStartDate(formatDateTimeInput(data[0].scanned_at));
            setCustomEndDate(formatDateTimeInput(data[0].scanned_at));
          } else if (data.length === 0) {
            setLoading(false);
          }
        } else {
          setLoading(false);
        }
      } catch (err) { console.error("Failed to fetch scans:", err); setLoading(false); }
    };
    fetchScans();
  }, [apiBase, kdNum]);

  useEffect(() => {
    const fetchAlliances = async () => {
      try {
        const res = await fetch(apiBase + "/kingdoms/" + kdNum + "/alliances");
        if (res.ok) {
          const data = await res.json();
          const names = (data || []).map((a: any) => a.name as string).filter(Boolean).sort();
          setAllianceList(names);
        }
      } catch (err) { /* ignore */ }
    };
    fetchAlliances();
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

  useEffect(() => {
    const fetchKvkSettings = async () => {
      try {
        const res = await fetch(apiBase + "/kingdoms/" + kdNum + "/kvk-settings");
        if (!res.ok) return;
        const data = await res.json();
        setKvkSettings(data);
        const configured = (data.war_periods || []).filter((period: WarPeriod) => period.configured);
        if (configured.length > 0) {
          setPeriodSelection((current) => current === "scan_range" ? "war_all" : current);
        }
      } catch (err) {
        console.error("Failed to fetch KvK settings:", err);
      }
    };
    fetchKvkSettings();
  }, [apiBase, kdNum]);

  useEffect(() => {
    if (!dkpWeights.dkp_enabled && sortBy === "dkp_score") {
      setSortBy("kill_points_gain");
      setSortDir("desc");
      setPage(1);
    }
  }, [dkpWeights.dkp_enabled, sortBy]);

  const buildGainsParams = useCallback((isSummary: boolean) => {
    const params = new URLSearchParams({
      skip: isSummary ? "0" : ((page - 1) * limit).toString(),
      limit: isSummary ? "10000" : limit.toString(),
      sort_by: sortBy === "dkp_score" ? "dead_gain" : sortBy,
      sort_dir: sortDir,
    });
    if (search) params.set("search", search);
    if (alliance) params.set("alliance", alliance);

    if (usingWarPeriods) {
      params.set("period_mode", "war_periods");
      if (periodSelection !== "war_all" && selectedWarIndex) {
        params.set("war_index", selectedWarIndex.toString());
      }
      return params;
    }

    if (usingCustomDates) {
      params.set("period_mode", "date_range");
      if (customStartDate) params.set("from_date", customStartDate);
      if (customEndDate) params.set("to_date", customEndDate);
      return params;
    }

    if (startScan) params.set("from_scan", startScan);
    if (endScan) params.set("to_scan", endScan);
    return params;
  }, [alliance, customEndDate, customStartDate, endScan, limit, page, periodSelection, search, selectedWarIndex, sortBy, sortDir, startScan, usingCustomDates, usingWarPeriods]);

  const calculatePlayersWithDkp = useCallback((items: any[]): PlayerData[] => {
    return items.map((x: any) => {
      const t4Part = (x.t4_kills_gain || 0) * dkpWeights.weight_t4;
      const t5Part = (x.t5_kills_gain || 0) * dkpWeights.weight_t5;
      const deadPart = (x.dead_gain || 0) * dkpWeights.weight_dead;
      let powerPenalty = 0;
      const playerPower = x.power || 0;

      if (dkpWeights.use_power_penalty) {
        if (dkpWeights.power_tiers && dkpWeights.power_tiers.length > 0) {
          const tier = dkpWeights.power_tiers.find(t => playerPower >= t.min_power && playerPower < t.max_power);
          if (tier && tier.power_coeff > 0) {
            powerPenalty = playerPower * tier.power_coeff;
          }
        }

        if (powerPenalty === 0 && playerPower > 0) {
          let defaultCoeff = 0.19;
          if (playerPower >= 90000000) defaultCoeff = 0.38;
          else if (playerPower >= 45000000) defaultCoeff = 0.30;
          powerPenalty = playerPower * defaultCoeff;
        }
      }

      const dkpScore = Math.round(t4Part + t5Part + deadPart - powerPenalty);
      return { ...x, power: playerPower, dkp_score: Math.max(0, dkpScore) };
    });
  }, [dkpWeights]);

  const summarizeItems = useCallback((items: any[], totalPlayers?: number): SummaryStats => {
    const summary: SummaryStats = {
      totalPlayers: totalPlayers || items.length,
      totalT4Kills: 0,
      totalT5Kills: 0,
      totalKillPoints: 0,
      totalDeaths: 0,
      totalPower: 0,
      totalAcclaimsGain: 0,
    };

    items.forEach((x: any) => {
      summary.totalT4Kills += x.t4_kills_gain || 0;
      summary.totalT5Kills += x.t5_kills_gain || 0;
      summary.totalKillPoints += x.kill_points_gain || 0;
      summary.totalDeaths += x.dead_gain || 0;
      summary.totalPower += x.power_gain || 0;
      summary.totalAcclaimsGain += x.acclaims_gain || 0;
    });

    return summary;
  }, []);

  const fetchAllMatchingGains = useCallback(async () => {
    const params = buildGainsParams(true);
    const endpoint = apiBase + "/kingdoms/" + kdNum + "/gains?";

    const initialRes = await fetch(endpoint + params.toString());
    if (!initialRes.ok) {
      return null;
    }

    const initialData = await initialRes.json();
    const initialItems = initialData.items || [];
    const total = initialData.total || initialItems.length;
    if (initialItems.length >= total) {
      return { items: initialItems, total };
    }

    params.set("limit", total.toString());
    const fullRes = await fetch(endpoint + params.toString());
    if (!fullRes.ok) {
      return { items: initialItems, total };
    }

    const fullData = await fullRes.json();
    return {
      items: fullData.items || initialItems,
      total: fullData.total || total,
    };
  }, [apiBase, buildGainsParams, kdNum]);

  const fetchData = useCallback(async () => {
    if (usingManualScans && (!startScan || !endScan)) return;
    if (usingCustomDates && (!customStartDate || !customEndDate)) return;

    if (usingCustomDates) {
      if (customStartDate > customEndDate) {
        setSelectionWarning("Start date must be before end date.");
        setPlayers([]);
        setTotalCount(0);
        setSummaryStats(null);
        setLoading(false);
        return;
      }
      setSelectionWarning(null);
    } else if (usingManualScans) {
      if (!selectedStartScan || !selectedEndScan) return;
      if (getScanComparisonGroup(selectedStartScan) !== getScanComparisonGroup(selectedEndScan)) {
        setSelectionWarning(`Selected scans come from incompatible sources (${getScanSourceLabel(selectedStartScan)} vs ${getScanSourceLabel(selectedEndScan)}). Compare profile scans with profile scans, or CSV imports with CSV imports.`);
        setPlayers([]);
        setTotalCount(0);
        setSummaryStats(null);
        setLoading(false);
        return;
      }
      setSelectionWarning(null);
    } else {
      setSelectionWarning(null);
    }

    setLoading(true);
    try {
      const isDkpSort = dkpWeights.dkp_enabled && sortBy === "dkp_score";

      if (isDkpSort) {
        const allData = await fetchAllMatchingGains();
        if (allData) {
          const playersWithDKP = calculatePlayersWithDkp(allData.items);
          playersWithDKP.sort((a: PlayerData, b: PlayerData) => sortDir === "desc" ? b.dkp_score - a.dkp_score : a.dkp_score - b.dkp_score);
          const startIdx = (page - 1) * limit;
          setPlayers(playersWithDKP.slice(startIdx, startIdx + limit));
          setTotalCount(allData.total || playersWithDKP.length);
          setSummaryStats(summarizeItems(playersWithDKP, allData.total || playersWithDKP.length));
        }
        return;
      }

      const p = buildGainsParams(false);
      const res = await fetch(apiBase + "/kingdoms/" + kdNum + "/gains?" + p);
      if (res.ok) {
        const data = await res.json();
        const items = data.items || [];
        setPlayers(calculatePlayersWithDkp(items));
        setTotalCount(data.total || 0);

        const allData = await fetchAllMatchingGains();
        if (allData) {
          setSummaryStats(summarizeItems(allData.items, allData.total || allData.items.length));
        } else {
          setSummaryStats(summarizeItems(items, data.total || items.length));
        }
      }
    } catch (err) { console.error("Failed to fetch data:", err); } finally { setLoading(false); }
  }, [apiBase, buildGainsParams, calculatePlayersWithDkp, customEndDate, customStartDate, dkpWeights.dkp_enabled, endScan, fetchAllMatchingGains, kdNum, limit, page, selectedEndScan, selectedStartScan, sortBy, sortDir, startScan, summarizeItems, usingCustomDates, usingManualScans]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const formatNumber = (n: number | null | undefined) => { if (n == null) return "0"; if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + "B"; if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + "M"; if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "K"; return n.toLocaleString(); };
  const getDisplayPeakPower = (player: PlayerData) => {
    const currentPower = player.power || 0;
    const reportedHighestPower = player.highest_power || 0;
    if (usingWarPeriods) return Math.max(reportedHighestPower, currentPower);
    const comparisonStartPower = currentPower - (player.power_gain || 0);
    return Math.max(reportedHighestPower, currentPower, comparisonStartPower);
  };
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
  const handleExportExcel = () => { const headers = ["Rank", "Name", "Alliance", "DKP Score", "Power", "Peak Power", "Acclaims", "Acclaims Gain", "Power Gain", "T1 Kills", "T2 Kills", "T3 Kills", "T4 Kills", "T5 Kills", "T4 KP", "T5 KP", "Deaths", "KP Gain"]; const rows = players.map((p, idx) => [(page - 1) * limit + idx + 1, `"${p.name.replace(/"/g, '""')}"`, `"${(p.alliance || '').replace(/"/g, '""')}"`, p.dkp_score, p.power, getDisplayPeakPower(p), p.acclaims || 0, p.acclaims_gain || 0, p.power_gain, p.t1_kills_gain || 0, p.t2_kills_gain || 0, p.t3_kills_gain || 0, p.t4_kills_gain, p.t5_kills_gain, p.t4_kp_gain || 0, p.t5_kp_gain || 0, p.dead_gain, p.kill_points_gain]); const csvContent = "\uFEFF" + [headers.join(","), ...rows.map(r => r.join(","))].join("\n"); const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" }); const url = window.URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "kd" + kdNum + "_rankings.csv"; a.click(); window.URL.revokeObjectURL(url); };

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div><h1 className="text-3xl font-bold text-accent">KD {kingdom} Dashboard</h1><p className="text-muted">Player rankings and statistics</p></div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-sm text-muted">Period:</label>
            <select value={periodSelection} onChange={(e) => { setPeriodSelection(e.target.value); setPage(1); }} className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent min-w-[220px]">
              <option value="scan_range">Manual Scan Range</option>
              <option value="custom_dates">Custom Date Range</option>
              {configuredWarPeriods.length > 0 && <option value="war_all">All Configured Wars</option>}
              {configuredWarPeriods.map((period) => (
                <option key={period.index} value={`war_${period.index}`}>
                  {period.label}: {formatDateTimeInput(period.start)} → {formatDateTimeInput(period.end)}
                </option>
              ))}
            </select>
          </div>
          {usingManualScans && <div className="flex items-center gap-2"><label className="text-sm text-muted">Start:</label><select value={startScan} onChange={(e) => { setStartScan(e.target.value); setPage(1); }} className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent min-w-[180px]">{scans.slice().reverse().map((s) => <option key={s.id} value={s.id}>{formatScanOptionLabel(s)}</option>)}</select></div>}
          {usingManualScans && <div className="flex items-center gap-2"><label className="text-sm text-muted">End:</label><select value={endScan} onChange={(e) => { setEndScan(e.target.value); setPage(1); }} className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent min-w-[180px]">{scans.map((s) => <option key={s.id} value={s.id}>{formatScanOptionLabel(s)}</option>)}</select></div>}
          {usingCustomDates && <div className="flex items-center gap-2"><label className="text-sm text-muted">From:</label><input type="datetime-local" value={customStartDate} onChange={(e) => { setCustomStartDate(e.target.value); setPage(1); }} className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent min-w-[210px]" /></div>}
          {usingCustomDates && <div className="flex items-center gap-2"><label className="text-sm text-muted">To:</label><input type="datetime-local" value={customEndDate} onChange={(e) => { setCustomEndDate(e.target.value); setPage(1); }} className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent min-w-[210px]" /></div>}
          <button onClick={handleExportExcel} className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>Export</button>
        </div>
      </div>
      {usingWarPeriods && (
        <div className="card bg-gradient-to-r from-amber-900/20 to-red-900/20 border-amber-500/30">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="font-semibold text-amber-300">War-Only Calculation Mode</h3>
              <p className="text-sm text-muted">The dashboard is summing gains only inside the configured war windows, so off-war feed does not inflate KvK numbers.</p>
            </div>
            {selectedWarLabel && <span className="text-xs px-3 py-1 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-200">{selectedWarLabel}</span>}
          </div>
        </div>
      )}
      {usingCustomDates && !selectionWarning && customStartDate && customEndDate && (
        <div className="card bg-gradient-to-r from-sky-900/30 to-cyan-900/20 border-sky-500/30">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="font-semibold text-sky-300">Custom Date Calculation</h3>
              <p className="text-sm text-muted">The dashboard is summing gains using snapshots inside the selected date window, with the nearest prior baseline used when needed.</p>
            </div>
            <span className="text-xs px-3 py-1 rounded-full border border-sky-500/30 bg-sky-500/10 text-sky-200">{customStartDate.replace("T", " ")} → {customEndDate.replace("T", " ")}</span>
          </div>
        </div>
      )}
      {!usingWarPeriods && selectionWarning && (
        <div className="card bg-gradient-to-r from-red-950/50 to-orange-900/30 border-red-500/40">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="font-semibold text-red-300">Selection Warning</h3>
              <p className="text-sm text-muted">{selectionWarning}</p>
            </div>
            <span className="text-xs px-3 py-1 rounded-full border border-red-500/40 bg-red-500/10 text-red-200">Adjust filters</span>
          </div>
        </div>
      )}
      {usingManualScans && !selectionWarning && selectedStartScan && selectedEndScan && selectedScanSourceLabel && (
        <div className="card bg-gradient-to-r from-slate-900/40 to-cyan-900/20 border-cyan-500/20">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="font-semibold text-cyan-300">Comparable Scan Window</h3>
              <p className="text-sm text-muted">Comparing {selectedScanSourceLabel} snapshots inside the same profile-scan pipeline, with monotonic stat reconciliation applied during clean imports.</p>
            </div>
            <span className="text-xs px-3 py-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 text-cyan-200">{selectedScanSourceLabel}</span>
          </div>
        </div>
      )}
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
      {summaryStats && <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4">
        <div className="card bg-gradient-to-br from-blue-900/50 to-blue-800/30 border-blue-500/30"><p className="text-xs text-blue-300 uppercase tracking-wider mb-1">Compared Players</p><p className="text-2xl font-bold text-white">{summaryStats.totalPlayers.toLocaleString()}</p></div>
        <div className="card bg-gradient-to-br from-cyan-900/50 to-cyan-800/30 border-cyan-500/30"><p className="text-xs text-cyan-300 uppercase tracking-wider mb-1">T4 Kills</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalT4Kills)}</p></div>
        <div className="card bg-gradient-to-br from-orange-900/50 to-orange-800/30 border-orange-500/30"><p className="text-xs text-orange-300 uppercase tracking-wider mb-1">T5 Kills</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalT5Kills)}</p></div>
        <div className="card bg-gradient-to-br from-green-900/50 to-green-800/30 border-green-500/30"><p className="text-xs text-green-300 uppercase tracking-wider mb-1">Total KP</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalKillPoints)}</p></div>
        <div className="card bg-gradient-to-br from-red-900/50 to-red-800/30 border-red-500/30"><p className="text-xs text-red-300 uppercase tracking-wider mb-1">Deaths</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalDeaths)}</p></div>
        <div className="card bg-gradient-to-br from-amber-900/50 to-yellow-800/30 border-amber-500/30"><p className="text-xs text-amber-300 uppercase tracking-wider mb-1">Acclaims Gain</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalAcclaimsGain)}</p></div>
        <div className="card bg-gradient-to-br from-purple-900/50 to-purple-800/30 border-purple-500/30"><p className="text-xs text-purple-300 uppercase tracking-wider mb-1">Power Gain</p><p className="text-2xl font-bold text-white">{formatNumber(summaryStats.totalPower)}</p></div>
      </div>}
      <div className="card"><div className="flex flex-col sm:flex-row gap-4"><div className="flex-1"><input type="text" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search by name or governor ID..." className="w-full bg-bg border border-border rounded-lg px-4 py-2.5 focus:outline-none focus:border-accent"/></div><div className="sm:w-56"><select value={alliance} onChange={(e) => { setAlliance(e.target.value); setPage(1); }} className="w-full bg-bg border border-border rounded-lg px-4 py-2.5 focus:outline-none focus:border-accent"><option value="">All Alliances</option>{allianceList.map(a => <option key={a} value={a}>{a}</option>)}</select></div></div></div>
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto -mx-4 sm:mx-0">
          <table className="w-full text-sm min-w-[940px]">
            <thead><tr className="border-b border-border bg-bg/80">
              <th className="text-left px-3 py-3 font-semibold text-muted">#</th>
              <th className="text-left px-3 py-3 font-semibold">PLAYER</th>
              {dkpWeights.dkp_enabled && <th className="text-right px-3 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("dkp_score")}><span className="text-yellow-400">DKP</span><SortIcon field="dkp_score" /></th>}
              <th className="text-right px-3 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("power")}>POWER<SortIcon field="power" /></th>
              <th className="text-right px-3 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("acclaims_gain")}><span className="text-amber-300">ACCLAIMS</span><SortIcon field="acclaims_gain" /></th>
              <th className="text-right px-3 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("dead_gain")}><span className="text-red-400">DEADS</span><SortIcon field="dead_gain" /></th>
              <th className="text-right px-3 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("t4_kills_gain")}><span className="text-blue-400">T4</span><SortIcon field="t4_kills_gain" /></th>
              <th className="text-right px-3 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("t5_kills_gain")}><span className="text-orange-400">T5</span><SortIcon field="t5_kills_gain" /></th>
              <th className="text-right px-3 py-3 font-semibold cursor-pointer hover:text-accent" onClick={() => handleSort("kill_points_gain")}>KP<SortIcon field="kill_points_gain" /></th>
            </tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={dkpWeights.dkp_enabled ? 9 : 8} className="text-center py-16 text-muted"><div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-accent mx-auto mb-3"></div>Loading...</td></tr> : players.length === 0 ? <tr><td colSpan={dkpWeights.dkp_enabled ? 9 : 8} className="text-center py-16 text-muted">No data found</td></tr> : players.map((player, idx) => {
                const rank = (page - 1) * limit + idx + 1;
                const dkpProgress = dkpWeights.dkp_enabled ? getDkpProgress(player.dkp_score, player.power, player.t4_kills_gain, player.t5_kills_gain, player.dead_gain) : null;
                const powerGrowth = player.power_gain > 0 ? "growing" : player.power_gain < 0 ? "dropping" : "idle";
                const displayPeakPower = getDisplayPeakPower(player);
                const acclaimsGrowth = player.acclaims_gain > 0 ? "growing" : player.acclaims_gain < 0 ? "dropping" : "idle";
                return <tr key={player.governor_id} className="border-b border-border/50 hover:bg-border/30 transition-colors">
                  <td className="px-3 py-3 text-muted font-mono">{rank}</td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-3">
                      <div className="relative">
                        <PlayerAvatar name={player.name} avatarUrl={player.avatar_url} />
                        <div className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full border-2 border-card ${powerGrowth === "growing" ? "bg-green-500" : powerGrowth === "dropping" ? "bg-red-500" : "bg-gray-500"}`} title={powerGrowth === "growing" ? "Power growing" : powerGrowth === "dropping" ? "Power dropping" : "No change"}></div>
                      </div>
                      <div>
                        <div className="font-medium">{player.name}</div>
                        {player.alliance && <span className="inline-block mt-0.5 px-2 py-0.5 bg-cyan-600/30 text-cyan-400 rounded text-xs font-medium">{player.alliance}</span>}
                      </div>
                    </div>
                  </td>
                  {dkpWeights.dkp_enabled && <td className="px-3 py-3">
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
                  <td className="px-3 py-3 text-right">
                    <div className="font-mono">{formatNumber(player.power)}</div>
                    {displayPeakPower > 0 && <div className="text-xs text-muted" title={usingWarPeriods ? "Peak power visible in current view" : "Peak observed power across the selected scan range"}>Peak {formatNumber(displayPeakPower)}</div>}
                    <div className={`text-xs font-medium ${player.power_gain > 0 ? 'text-green-400' : player.power_gain < 0 ? 'text-red-400' : 'text-gray-500'}`}>{player.power_gain > 0 ? '+' : ''}{formatNumber(player.power_gain)} {player.power_gain > 0 ? '▲' : player.power_gain < 0 ? '▼' : ''}</div>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <div className="font-mono text-white">{formatNumber(player.acclaims)}</div>
                    <div className={`text-xs font-medium ${acclaimsGrowth === 'growing' ? 'text-green-400' : acclaimsGrowth === 'dropping' ? 'text-red-400' : 'text-gray-500'}`}>{player.acclaims_gain > 0 ? '+' : ''}{formatNumber(player.acclaims_gain)} {player.acclaims_gain > 0 ? '▲' : player.acclaims_gain < 0 ? '▼' : ''}</div>
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-white">{formatNumber(player.dead_gain)}</td>
                  <td className="px-3 py-3 text-right font-mono text-white">{formatNumber(player.t4_kills_gain)}</td>
                  <td className="px-3 py-3 text-right font-mono text-white">{formatNumber(player.t5_kills_gain)}</td>
                  <td className="px-3 py-3 text-right font-mono text-white">{formatNumber(player.kill_points_gain)}</td>
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