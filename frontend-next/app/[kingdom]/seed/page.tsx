"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useMemo } from "react";

interface SeedData {
  // Core matchmaking values (what Lilith uses)
  top300Power: number;           // Sum of TOP 300 players power - PRIMARY METRIC
  top300KillPoints: number;      // Sum of TOP 300 players kill points
  top300Deads: number;           // Sum of TOP 300 players deads
  
  // Supporting metrics - CH25 ONLY counts for seed
  ch25Players: number;           // Players with power >= threshold (estimated CH25+)
  ch25TotalPower: number;        // Total power of CH25+ players
  totalPlayers: number;          // Total scanned players
  
  // Estimation
  estimatedSeed: string;
  
  // Player counts at tiers
  count40M: number;
  count60M: number;
  count80M: number;
  count100M: number;
  
  // CH25 breakdown
  ch25Breakdown: {
    range: string;
    count: number;
    totalPower: number;
    percentage: number;
  }[];
  
  // CH25 players list
  ch25PlayersList: PlayerData[];
}

interface PlayerData {
  governor_id: number;
  name: string;
  alliance: string | null;
  power: number;
  killpoints?: number;
  deads?: number;
}

/**
 * KvK SEED MATCHMAKING SYSTEM
 * Based on community research (Reddit, RoKBoard, etc.):
 * 
 * PRIMARY FACTOR: Total power of TOP 300 players
 * - Lilith sums the power of the kingdom's top 300 players
 * - This creates the initial "filter set" for matchmaking
 * - Kingdoms are grouped within ±15% of average top 300 power
 * 
 * SECONDARY FACTORS (after power grouping):
 * - Kill points of top 300 players
 * - Dead troops of top 300 players
 * - Active player count
 * - Available commanders
 * - Previous KvK results
 * - Language preference
 * 
 * SEED BRACKETS (estimated from community data):
 * - Seed A: TOP 300 total > 25B power
 * - Seed B: TOP 300 total 18-25B power
 * - Seed C: TOP 300 total 12-18B power
 * - Seed D: TOP 300 total < 12B power
 */

const SEED_BRACKETS = {
  A: { 
    minTop300Power: 25_000_000_000,  // 25B total top 300 power
    label: "A", 
    color: "from-yellow-400 to-amber-500", 
    textColor: "text-yellow-400",
    description: "Top Tier Kingdom",
    avgPlayer: "83M average per top 300 player"
  },
  B: { 
    minTop300Power: 18_000_000_000,  // 18B total
    label: "B", 
    color: "from-gray-300 to-gray-400", 
    textColor: "text-gray-300",
    description: "Competitive Kingdom",
    avgPlayer: "60M average per top 300 player"
  },
  C: { 
    minTop300Power: 12_000_000_000,  // 12B total
    label: "C", 
    color: "from-orange-500 to-orange-600", 
    textColor: "text-orange-400",
    description: "Growing Kingdom",
    avgPlayer: "40M average per top 300 player"
  },
  D: { 
    minTop300Power: 0,
    label: "D", 
    color: "from-stone-500 to-stone-600", 
    textColor: "text-stone-400",
    description: "Developing Kingdom",
    avgPlayer: "Under 40M average per top 300 player"
  },
};

// CH25 minimum power threshold (typical minimum for CH25 players - user configurable)
const DEFAULT_CH25_POWER_THRESHOLD = 25_000_000;

export default function SeedAnalysisPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const [loading, setLoading] = useState(true);
  const [players, setPlayers] = useState<PlayerData[]>([]);
  const [showCh25List, setShowCh25List] = useState(false);
  const [ch25Threshold, setCh25Threshold] = useState(DEFAULT_CH25_POWER_THRESHOLD);
  
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  useEffect(() => {
    const fetchPlayers = async () => {
      setLoading(true);
      try {
        // Fetch all players to calculate seed - need TOP 300
        const res = await fetch(`${apiBase}/kingdoms/${kdNum}/governors?skip=0&limit=10000&sort_by=power&sort_dir=desc`);
        if (res.ok) {
          const data = await res.json();
          setPlayers(data.items || []);
        }
      } catch (err) {
        console.error("Failed to fetch players:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchPlayers();
  }, [apiBase, kdNum]);

  // Calculate seed data using CH25 players ONLY (only CH25 counts for KvK seed)
  const seedData = useMemo<SeedData | null>(() => {
    if (players.length === 0) return null;

    // Filter to CH25+ players only (using user-defined threshold)
    const ch25PlayersList = players
      .filter(p => p.power >= ch25Threshold)
      .sort((a, b) => b.power - a.power);
    
    // PRIMARY METRIC: Total power of CH25 players
    const top300Power = ch25PlayersList.reduce((sum, p) => sum + p.power, 0);
    const top300KillPoints = ch25PlayersList.reduce((sum, p) => sum + (p.killpoints || 0), 0);
    const top300Deads = ch25PlayersList.reduce((sum, p) => sum + (p.deads || 0), 0);
    
    // Count players at different power tiers (from CH25 only)
    const count40M = ch25PlayersList.filter(p => p.power >= 40_000_000).length;
    const count60M = ch25PlayersList.filter(p => p.power >= 60_000_000).length;
    const count80M = ch25PlayersList.filter(p => p.power >= 80_000_000).length;
    const count100M = ch25PlayersList.filter(p => p.power >= 100_000_000).length;

    // Calculate power distribution for CH25 players
    const powerRanges = [
      { range: "100M+", min: 100_000_000, max: Infinity },
      { range: "80M-100M", min: 80_000_000, max: 100_000_000 },
      { range: "60M-80M", min: 60_000_000, max: 80_000_000 },
      { range: "40M-60M", min: 40_000_000, max: 60_000_000 },
      { range: "25M-40M", min: 25_000_000, max: 40_000_000 },
    ];

    const ch25Breakdown = powerRanges.map(r => {
      const inRange = ch25PlayersList.filter(p => p.power >= r.min && p.power < r.max);
      return {
        range: r.range,
        count: inRange.length,
        totalPower: inRange.reduce((sum, p) => sum + p.power, 0),
        percentage: ch25PlayersList.length > 0 ? (inRange.length / ch25PlayersList.length) * 100 : 0,
      };
    });

    // Determine seed based on CH25 TOTAL POWER
    let estimatedSeed = "D";
    if (top300Power >= SEED_BRACKETS.A.minTop300Power) {
      estimatedSeed = "A";
    } else if (top300Power >= SEED_BRACKETS.B.minTop300Power) {
      estimatedSeed = "B";
    } else if (top300Power >= SEED_BRACKETS.C.minTop300Power) {
      estimatedSeed = "C";
    }

    return {
      top300Power,
      top300KillPoints,
      top300Deads,
      ch25Players: ch25PlayersList.length,
      ch25TotalPower: top300Power,
      totalPlayers: players.length,
      estimatedSeed,
      count40M,
      count60M,
      count80M,
      count100M,
      ch25Breakdown,
      ch25PlayersList,
    };
  }, [players, ch25Threshold]);

  const formatPower = (n: number | null | undefined) => {
    if (n == null) return "0";
    if (n >= 1e12) return (n / 1e12).toFixed(2) + "T";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toLocaleString();
  };

  const currentSeedData = seedData ? SEED_BRACKETS[seedData.estimatedSeed as keyof typeof SEED_BRACKETS] : null;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-accent/30 border-t-accent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-text-muted">Analyzing kingdom data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
            <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <div>
            <h1 className="text-3xl font-bold">KvK Seed Analysis</h1>
            <p className="text-text-muted">Kingdom {kingdom} matchmaking classification</p>
          </div>
        </div>
      </div>

      {/* Info Banner - Updated with correct info */}
      <div className="card bg-gradient-to-r from-blue-900/30 to-purple-900/30 border-blue-500/30">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center flex-shrink-0">
            <svg className="w-6 h-6 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div>
            <h3 className="font-bold text-lg text-blue-300 mb-2">How KvK Seed Matchmaking Works</h3>
            <ul className="text-text-secondary text-sm space-y-1.5">
              <li className="flex items-start gap-2">
                <span className="text-yellow-400 mt-0.5 font-bold">1.</span>
                <span><strong className="text-white">Primary Factor:</strong> Total power of <strong className="text-yellow-400">City Hall 25+ players ONLY</strong></span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-400 mt-0.5 font-bold">2.</span>
                <span><strong className="text-white">CH25 Detection:</strong> We cannot see CH level directly, but you can estimate using power threshold below</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-purple-400 mt-0.5 font-bold">3.</span>
                <span><strong className="text-white">Secondary Factors:</strong> Kill Points, Dead Troops, active players, commanders</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-green-400 mt-0.5 font-bold">4.</span>
                <span>Kingdoms grouped within ±15% of average CH25 power, then further filtered</span>
              </li>
            </ul>
            <p className="text-xs text-text-muted mt-3 italic">Source: Community research - only CH25+ players count for seed matchmaking</p>
          </div>
        </div>
      </div>

      {/* CH25 Power Threshold Slider */}
      <div className="card bg-gradient-to-r from-cyan-900/20 to-blue-900/20 border-cyan-500/30">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-cyan-500/20 flex items-center justify-center flex-shrink-0">
            <svg className="w-6 h-6 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
            </svg>
          </div>
          <div className="flex-1">
            <h3 className="font-bold text-lg text-cyan-300 mb-2">CH25 Power Threshold</h3>
            <p className="text-text-muted text-sm mb-4">
              Since we cannot see City Hall level directly, set the minimum power threshold you consider as CH25+. 
              Only players above this threshold will count for seed calculation.
            </p>
            <div className="space-y-3">
              <div className="flex items-center gap-4">
                <input 
                  type="range" 
                  min="15000000" 
                  max="40000000" 
                  step="1000000"
                  value={ch25Threshold}
                  onChange={(e) => setCh25Threshold(parseInt(e.target.value))}
                  className="flex-1 h-2 bg-bg-secondary rounded-lg appearance-none cursor-pointer accent-cyan-500"
                />
                <div className="w-24 text-right">
                  <span className="text-2xl font-bold text-cyan-400">{(ch25Threshold / 1_000_000)}M</span>
                </div>
              </div>
              <div className="flex justify-between text-xs text-text-muted">
                <span>15M</span>
                <span>25M</span>
                <span>40M</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {seedData && (
        <>
          {/* Main Seed Display */}
          <div className="grid lg:grid-cols-3 gap-6">
            {/* Seed Badge */}
            <div className="lg:col-span-1">
              <div className="card h-full flex flex-col items-center justify-center py-10">
                <p className="text-text-muted text-sm uppercase tracking-wider mb-4">Estimated Seed</p>
                <div className={`w-32 h-32 rounded-3xl bg-gradient-to-br ${currentSeedData?.color} flex items-center justify-center shadow-2xl mb-6`}>
                  <span className="text-7xl font-black text-white drop-shadow-lg">{seedData.estimatedSeed}</span>
                </div>
                <p className="text-text-secondary text-center mb-2">
                  {currentSeedData?.description}
                </p>
                <p className="text-xs text-text-muted text-center">
                  {currentSeedData?.avgPlayer}
                </p>
                <div className="mt-4 px-4 py-2 bg-cyan-500/10 border border-cyan-500/30 rounded-xl">
                  <span className="text-cyan-400 text-xs font-bold">{seedData.ch25Players} CH25+ players</span>
                </div>
              </div>
            </div>

            {/* Key Metrics - CH25 FOCUSED */}
            <div className="lg:col-span-2 grid grid-cols-2 gap-4">
              {/* PRIMARY METRIC */}
              <div className="col-span-2 card relative overflow-hidden bg-gradient-to-r from-yellow-900/20 to-amber-900/20 border-yellow-500/30">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-yellow-400 to-amber-500" />
                <div className="flex items-center gap-2 mb-2">
                  <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 text-xs font-bold rounded">PRIMARY</span>
                  <p className="text-text-muted text-xs uppercase tracking-wider">CH25+ Total Power</p>
                </div>
                <p className="text-4xl font-bold text-yellow-400">{formatPower(seedData.top300Power)}</p>
                <p className="text-text-muted text-sm mt-1">
                  Based on {seedData.ch25Players} players with power ≥ {formatPower(ch25Threshold)}
                </p>
              </div>
              
              <div className="card relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-500 to-cyan-500" />
                <div className="flex items-center gap-2 mb-2">
                  <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs font-bold rounded">CH25+</span>
                  <p className="text-text-muted text-xs uppercase tracking-wider">City Hall 25+ Players</p>
                </div>
                <p className="text-3xl font-bold text-blue-400">{seedData.ch25Players}</p>
                <p className="text-text-muted text-xs mt-1 italic">Players ≥ {formatPower(ch25Threshold)} power</p>
              </div>
              <div className="card relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-purple-500 to-pink-500" />
                <p className="text-text-muted text-xs uppercase tracking-wider mb-2">Avg CH25 Power</p>
                <p className="text-3xl font-bold text-purple-400">{formatPower(seedData.ch25Players > 0 ? seedData.top300Power / seedData.ch25Players : 0)}</p>
                <p className="text-text-muted text-sm mt-1">Per player</p>
              </div>
              <div className="card relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-orange-500 to-amber-500" />
                <p className="text-text-muted text-xs uppercase tracking-wider mb-2">Players 60M+</p>
                <p className="text-3xl font-bold text-orange-400">{seedData.count60M}</p>
                <p className="text-text-muted text-sm mt-1">Strong fighters</p>
              </div>
              <div className="card relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-red-500 to-pink-500" />
                <p className="text-text-muted text-xs uppercase tracking-wider mb-2">Players 80M+</p>
                <p className="text-3xl font-bold text-red-400">{seedData.count80M}</p>
                <p className="text-text-muted text-sm mt-1">Elite players</p>
              </div>
            </div>
          </div>

          {/* CH25 Power Distribution */}
          <div className="card">
            <h3 className="font-bold text-lg mb-6">CH25+ Power Distribution</h3>
            <div className="space-y-4">
              {seedData.ch25Breakdown.filter(r => r.count > 0).map((range, idx) => (
                <div key={range.range}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium">{range.range}</span>
                    <span className="text-text-muted">
                      <span className="text-white font-bold">{range.count}</span> players • {formatPower(range.totalPower)}
                    </span>
                  </div>
                  <div className="h-3 bg-bg-secondary rounded-full overflow-hidden">
                    <div 
                      className={`h-full rounded-full transition-all duration-500 ${
                        idx === 0 ? "bg-gradient-to-r from-yellow-500 to-amber-500" :
                        idx === 1 ? "bg-gradient-to-r from-purple-500 to-pink-500" :
                        idx === 2 ? "bg-gradient-to-r from-blue-500 to-cyan-500" :
                        idx === 3 ? "bg-gradient-to-r from-green-500 to-emerald-500" :
                        idx === 4 ? "bg-gradient-to-r from-orange-500 to-red-500" :
                        "bg-gradient-to-r from-gray-500 to-gray-600"
                      }`}
                      style={{ width: `${Math.max(range.percentage, 2)}%` }}
                    />
                  </div>
                  <p className="text-right text-text-muted text-sm mt-1">{range.percentage.toFixed(1)}%</p>
                </div>
              ))}
            </div>
          </div>

          {/* Seed Brackets Comparison Table */}
          <div className="card overflow-hidden p-0">
            <div className="px-6 py-4 border-b border-border/50">
              <h3 className="font-bold text-lg">Seed Bracket Thresholds</h3>
              <p className="text-text-muted text-sm">Based on CH25+ total power (community research estimates)</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 bg-bg-secondary/50">
                    <th className="text-left px-6 py-4 font-semibold text-text-muted">Seed</th>
                    <th className="text-right px-6 py-4 font-semibold text-text-muted">Min CH25 Power</th>
                    <th className="text-center px-6 py-4 font-semibold text-text-muted">Your Status</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(SEED_BRACKETS).map(([seed, data]) => {
                    const currentPower = seedData.top300Power;
                    const meetsCriteria = currentPower >= data.minTop300Power;
                    const isCurrent = seed === seedData.estimatedSeed;
                    return (
                      <tr key={seed} className={`border-b border-border/30 ${isCurrent ? "bg-accent/10" : ""}`}>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${data.color} flex items-center justify-center`}>
                              <span className="text-xl font-black text-white">{seed}</span>
                            </div>
                            <div>
                              <p className="font-medium">{data.description}</p>
                              {isCurrent && (
                                <span className="px-2 py-0.5 bg-accent/20 text-accent text-xs font-bold rounded">CURRENT</span>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <span className={meetsCriteria ? "text-green-400 font-bold" : "text-text-muted"}>
                            {seed === "D" ? "< " + formatPower(SEED_BRACKETS.C.minTop300Power) : formatPower(data.minTop300Power) + "+"}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-center">
                          {meetsCriteria && seed !== "D" ? (
                            <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-500/20 text-green-400 rounded-lg text-xs font-semibold">
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                              </svg>
                              Qualifies
                            </span>
                          ) : seed === "D" && seedData.estimatedSeed === "D" ? (
                            <span className="inline-flex items-center gap-1 px-3 py-1 bg-stone-500/20 text-stone-400 rounded-lg text-xs font-semibold">
                              Current
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-3 py-1 bg-red-500/20 text-red-400 rounded-lg text-xs font-semibold">
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                              Below
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-6 py-4 bg-bg-secondary/30 border-t border-border/50">
              <p className="text-text-muted text-sm">
                Your CH25+ Power: <strong className="text-white">{formatPower(seedData.top300Power)}</strong>
                <span className="text-cyan-400 ml-2">({seedData.ch25Players} players ≥ {formatPower(ch25Threshold)})</span>
              </p>
            </div>
          </div>

          {/* Toggle CH25 List */}
          <div className="card">
            <button
              onClick={() => setShowCh25List(!showCh25List)}
              className="w-full flex items-center justify-between"
            >
              <div>
                <h3 className="font-bold text-lg">CH25+ Players ({seedData.ch25Players})</h3>
                <p className="text-text-muted text-sm">View the players that determine your seed (power ≥ {formatPower(ch25Threshold)})</p>
              </div>
              <svg 
                className={`w-6 h-6 text-text-muted transition-transform ${showCh25List ? "rotate-180" : ""}`} 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            
            {showCh25List && (
              <div className="mt-6 max-h-96 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-bg-card">
                    <tr className="border-b border-border/50">
                      <th className="text-left px-4 py-2 font-semibold text-text-muted">#</th>
                      <th className="text-left px-4 py-2 font-semibold text-text-muted">Name</th>
                      <th className="text-left px-4 py-2 font-semibold text-text-muted">Alliance</th>
                      <th className="text-right px-4 py-2 font-semibold text-text-muted">Power</th>
                    </tr>
                  </thead>
                  <tbody>
                    {seedData.ch25PlayersList.map((player, idx) => (
                      <tr key={player.governor_id} className="border-b border-border/20 hover:bg-bg-secondary/30">
                        <td className="px-4 py-2 text-text-muted">{idx + 1}</td>
                        <td className="px-4 py-2 font-medium">{player.name}</td>
                        <td className="px-4 py-2 text-text-muted">{player.alliance || "-"}</td>
                        <td className="px-4 py-2 text-right font-mono text-accent">{formatPower(player.power)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          {seedData.estimatedSeed !== "A" && (
            <div className="card bg-gradient-to-r from-green-900/20 to-emerald-900/20 border-green-500/30">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-green-500/20 flex items-center justify-center flex-shrink-0">
                  <svg className="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                  </svg>
                </div>
                <div>
                  <h3 className="font-bold text-lg text-green-300 mb-3">How to Improve Your Seed</h3>
                  <ul className="text-text-secondary text-sm space-y-2">
                    {seedData.estimatedSeed === "D" && (
                      <>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>Focus on recruiting or growing accounts to increase TOP 300 total power</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>Need <strong className="text-white">{formatPower(SEED_BRACKETS.C.minTop300Power - seedData.top300Power)}</strong> more total power for Seed C</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>That&apos;s about <strong className="text-white">{formatPower((SEED_BRACKETS.C.minTop300Power - seedData.top300Power) / 300)}</strong> more per player on average</span>
                        </li>
                      </>
                    )}
                    {seedData.estimatedSeed === "C" && (
                      <>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>Continue developing your TOP 300 players</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>Need <strong className="text-white">{formatPower(SEED_BRACKETS.B.minTop300Power - seedData.top300Power)}</strong> more total power for Seed B</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>Average TOP 300 player needs to be <strong className="text-white">{formatPower(SEED_BRACKETS.B.minTop300Power / 300)}</strong></span>
                        </li>
                      </>
                    )}
                    {seedData.estimatedSeed === "B" && (
                      <>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>You&apos;re close to Seed A! Keep growing your TOP 300</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>Need <strong className="text-white">{formatPower(SEED_BRACKETS.A.minTop300Power - seedData.top300Power)}</strong> more total power for Seed A</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-green-400">•</span>
                          <span>Average TOP 300 player needs to be <strong className="text-white">{formatPower(SEED_BRACKETS.A.minTop300Power / 300)}</strong></span>
                        </li>
                      </>
                    )}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
