"use client";
import { useEffect, useState, useCallback, useRef } from "react";

/* ── Types ────────────────────────────────────────────────────────── */

interface PlayerLoc {
  governor_id: number;
  governor_name: string;
  x: number;
  y: number;
  power: number | null;
  alliance_tag: string | null;
  alliance_name: string | null;
  city_level: number | null;
  char_type: number | null;
  shield_type: string | null;
  shield_expires_at: string | null;
  scan_id: string | null;
  updated_at: string;
}

interface CoordShare {
  id: number;
  x: number;
  y: number;
  shared_by: string | null;
  target_type: string | null;
  location: string | null;
  captured_at: string;
}

interface ChatCoord {
  id: number;
  x: number;
  y: number;
  shared_by: string | null;
  alliance: string | null;
  text: string | null;
  location: string | null;
  captured_at: string;
}

interface MapData {
  player_locations: PlayerLoc[];
  coordinate_shares: CoordShare[];
  chat_coordinates: ChatCoord[];
}

interface FinderResult {
  governor_id: number;
  governor_name: string;
  x: number;
  y: number;
  power: number;
  kill: number;
  kill_score: number;
  city_level: number;
  civilization: number;
  alliance_id: number;
  alliance_tag: string;
  alliance_name: string;
  temple_title: number;
  fighting: boolean;
  shield_end_time: number | null;
  shield_remaining_seconds: number | null;
  shield_type: string | null;
  linked_accounts: { governor_id: number; governor_name: string; is_main: boolean }[];
}

interface FinderStatus {
  status: "no_request" | "searching" | "found" | "not_found" | "error";
  governor_id?: number;
  progress?: string;
  result?: FinderResult;
  created_at?: string;
  updated_at?: string;
}

type LayerKey = "players" | "coords" | "chat";

/* ── Constants ────────────────────────────────────────────────────── */

const COLORS = {
  players: { fill: "#3b82f6", ring: "#60a5fa", label: "Players" },
  coords: { fill: "#22c55e", ring: "#4ade80", label: "Coord Shares" },
  chat: { fill: "#f59e0b", ring: "#fbbf24", label: "Chat Coords" },
  shielded: { fill: "#a855f7", ring: "#c084fc", label: "Shielded" },
};

const MAP_SIZE = 1200;

/* ── Helpers ──────────────────────────────────────────────────────── */

function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function formatShieldTime(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h >= 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h ${m}m`;
  }
  return `${h}h ${m}m`;
}

function shieldTimeRemaining(expiresAt: string | null): string | null {
  if (!expiresAt) return null;
  const remaining = (new Date(expiresAt).getTime() - Date.now()) / 1000;
  if (remaining <= 0) return null;
  return formatShieldTime(remaining);
}

function formatPower(n: number | null): string {
  if (!n) return "—";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

/* ── Component ────────────────────────────────────────────────────── */

export default function MapPanel({
  kingdom,
  token,
  isBotConnected,
}: {
  kingdom: string;
  token: string | null;
  isBotConnected: boolean;
}) {
  /* -- Map state -- */
  const [data, setData] = useState<MapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    players: true,
    coords: true,
    chat: true,
  });
  const [hovered, setHovered] = useState<{
    type: string;
    x: number;
    y: number;
    label: string;
    extra?: string;
  } | null>(null);
  const [search, setSearch] = useState("");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  /* -- Player Finder state -- */
  const [govId, setGovId] = useState("");
  const [finderStatus, setFinderStatus] = useState<FinderStatus>({ status: "no_request" });
  const [searching, setSearching] = useState(false);
  const [finderError, setFinderError] = useState<string | null>(null);
  const [showFinder, setShowFinder] = useState(false);

  /* -- Map scan state -- */
  const [startingMapScan, setStartingMapScan] = useState(false);

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  /* -- Map data fetching -- */
  const fetchMap = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kingdom}/map/locations`);
      if (res.ok) setData(await res.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [apiBase, kingdom]);

  useEffect(() => {
    fetchMap();
  }, [fetchMap]);

  /* -- Player Finder -- */
  const pollFinderStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kingdom}/bot/find-player`);
      if (res.ok) {
        const d = await res.json();
        setFinderStatus(d);
        if (d.status === "found" || d.status === "not_found" || d.status === "error") {
          setSearching(false);
        }
      }
    } catch {
      /* ignore */
    }
  }, [apiBase, kingdom]);

  useEffect(() => {
    if (!searching) return;
    const interval = setInterval(pollFinderStatus, 2000);
    return () => clearInterval(interval);
  }, [searching, pollFinderStatus]);

  useEffect(() => {
    pollFinderStatus().then(() => {
      setFinderStatus((prev) => {
        if (prev.status === "searching") setSearching(true);
        return prev;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startSearch = async () => {
    const id = parseInt(govId);
    if (!id || id <= 0) {
      setFinderError("Enter a valid Governor ID");
      return;
    }
    setFinderError(null);
    setSearching(true);
    setFinderStatus({ status: "searching", progress: "Sending request..." });
    try {
      const params = new URLSearchParams({ governor_id: String(id) });
      const res = await fetch(`${apiBase}/kingdoms/${kingdom}/bot/find-player?${params}`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setFinderError(err.detail || "Request failed");
        setSearching(false);
        return;
      }
      pollFinderStatus();
    } catch (e) {
      setFinderError(String(e));
      setSearching(false);
    }
  };

  /* -- Layer toggles -- */
  const toggleLayer = (key: LayerKey) =>
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));

  /* -- Map scan trigger -- */
  const startMapScan = async () => {
    if (!token) return;
    setStartingMapScan(true);
    try {
      const p = new URLSearchParams({ command: "start_map_scan" });
      await fetch(`${apiBase}/kingdoms/${kingdom}/bot/command?${p}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
    } catch { /* ignore */ }
    finally { setStartingMapScan(false); }
  };

  /* -- Points for canvas -- */
  const getPoints = useCallback(() => {
    if (!data) return [];
    const pts: {
      x: number;
      y: number;
      type: LayerKey;
      label: string;
      extra?: string;
      shielded?: boolean;
    }[] = [];
    if (layers.players) {
      for (const p of data.player_locations) {
        if (search && !p.governor_name.toLowerCase().includes(search.toLowerCase())) continue;
        const shieldLeft = shieldTimeRemaining(p.shield_expires_at);
        pts.push({
          x: p.x,
          y: p.y,
          type: "players",
          label: p.governor_name,
          extra: shieldLeft
            ? `🛡 ${shieldLeft}`
            : p.power
              ? formatPower(p.power)
              : undefined,
          shielded: !!p.shield_type,
        });
      }
    }
    if (layers.coords) {
      for (const c of data.coordinate_shares) {
        pts.push({ x: c.x, y: c.y, type: "coords", label: c.shared_by || "Unknown", extra: c.target_type || undefined });
      }
    }
    if (layers.chat) {
      for (const c of data.chat_coordinates) {
        if (search && !(c.shared_by || "").toLowerCase().includes(search.toLowerCase())) continue;
        pts.push({ x: c.x, y: c.y, type: "chat", label: c.shared_by || "Unknown", extra: c.text || undefined });
      }
    }
    return pts;
  }, [data, layers, search]);

  /* -- Canvas drawing -- */
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const size = Math.min(container.clientWidth, 700);
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const scale = size / MAP_SIZE;

    ctx.fillStyle = "#0a0a0f";
    ctx.fillRect(0, 0, size, size);

    ctx.strokeStyle = "#1e1e2e";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= MAP_SIZE; i += 100) {
      const p = i * scale;
      ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, size); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(size, p); ctx.stroke();
    }
    ctx.fillStyle = "#3f3f46";
    ctx.font = "9px monospace";
    for (let i = 0; i <= MAP_SIZE; i += 200) {
      ctx.fillText(String(i), i * scale + 2, 10);
      ctx.fillText(String(i), 2, i * scale + 10);
    }

    const points = getPoints();
    for (const pt of points) {
      const px = pt.x * scale;
      const py = pt.y * scale;
      const color = pt.shielded ? COLORS.shielded : COLORS[pt.type];
      ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2); ctx.fillStyle = color.ring + "40"; ctx.fill();
      ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI * 2); ctx.fillStyle = color.fill; ctx.fill();
    }

    if (hovered) {
      const px = hovered.x * scale;
      const py = hovered.y * scale;
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 11px sans-serif";
      ctx.fillText(hovered.label, px + 8, py - 4);
      ctx.fillStyle = "#a1a1aa";
      ctx.font = "9px sans-serif";
      ctx.fillText(`(${hovered.x}, ${hovered.y})`, px + 8, py + 8);
    }
  }, [data, layers, search, hovered, getPoints]);

  /* -- Canvas hover -- */
  const handleCanvasMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const scale = canvas.width / MAP_SIZE;
      const points = getPoints();
      let closest: (typeof points)[0] | null = null;
      let closestDist = 15;
      for (const pt of points) {
        const dx = pt.x * scale - mx;
        const dy = pt.y * scale - my;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < closestDist) { closestDist = dist; closest = pt; }
      }
      if (closest) {
        setHovered({ type: closest.type, x: closest.x, y: closest.y, label: closest.label, extra: closest.extra });
      } else {
        setHovered(null);
      }
    },
    [getPoints],
  );

  /* -- Derived -- */
  const points = getPoints();
  const totalPlayers = data?.player_locations.length ?? 0;
  const totalCoords = data?.coordinate_shares.length ?? 0;
  const totalChat = data?.chat_coordinates.length ?? 0;
  const shielded = data?.player_locations.filter((p) => p.shield_type).length ?? 0;
  const finderResult = finderStatus.result;
  const isSearching = finderStatus.status === "searching";

  /* -- Loading -- */
  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-accent" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-surface border border-gray-700/50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-blue-400">{totalPlayers}</div>
          <div className="text-xs text-gray-400">Player Locations</div>
        </div>
        <div className="bg-surface border border-gray-700/50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-purple-400">{shielded}</div>
          <div className="text-xs text-gray-400">Shielded</div>
        </div>
        <div className="bg-surface border border-gray-700/50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-green-400">{totalCoords}</div>
          <div className="text-xs text-gray-400">Coord Shares</div>
        </div>
        <div className="bg-surface border border-gray-700/50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-amber-400">{totalChat}</div>
          <div className="text-xs text-gray-400">Chat Coords</div>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search player name…"
          className="px-3 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 focus:border-blue-500 outline-none text-sm w-56"
        />
        <button onClick={() => toggleLayer("players")} className={`flex items-center gap-1.5 px-3 py-1 rounded text-sm border transition-colors ${layers.players ? "border-blue-500/40 bg-blue-500/10 text-blue-400" : "border-zinc-700 bg-zinc-800/50 text-zinc-500"}`}>
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: layers.players ? COLORS.players.fill : "#52525b" }} />
          {COLORS.players.label}
        </button>
        <button onClick={() => toggleLayer("coords")} className={`flex items-center gap-1.5 px-3 py-1 rounded text-sm border transition-colors ${layers.coords ? "border-green-500/40 bg-green-500/10 text-green-400" : "border-zinc-700 bg-zinc-800/50 text-zinc-500"}`}>
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: layers.coords ? COLORS.coords.fill : "#52525b" }} />
          {COLORS.coords.label}
        </button>
        <button onClick={() => toggleLayer("chat")} className={`flex items-center gap-1.5 px-3 py-1 rounded text-sm border transition-colors ${layers.chat ? "border-amber-500/40 bg-amber-500/10 text-amber-400" : "border-zinc-700 bg-zinc-800/50 text-zinc-500"}`}>
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: layers.chat ? COLORS.chat.fill : "#52525b" }} />
          {COLORS.chat.label}
        </button>
        <button
          onClick={() => setShowFinder(!showFinder)}
          className={`flex items-center gap-1.5 px-3 py-1 rounded text-sm border transition-colors ${
            showFinder ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-400" : "border-zinc-700 bg-zinc-800/50 text-zinc-400 hover:text-zinc-200"
          }`}
        >
          🔍 Player Finder
        </button>
        <div className="flex items-center gap-2 ml-auto">
          {isBotConnected && token && (
            <button
              onClick={startMapScan}
              disabled={startingMapScan}
              className="px-3 py-1 text-xs rounded bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white font-medium transition-colors flex items-center gap-1.5"
            >
              {startingMapScan ? "Starting..." : "🗺️ Scan Map"}
            </button>
          )}
          <span className="text-sm text-zinc-500">{points.length} points</span>
          <button onClick={fetchMap} className="px-2 py-1 text-xs rounded bg-zinc-700 hover:bg-zinc-600 transition-colors">↻</button>
        </div>
      </div>

      {/* Player Finder (collapsible) */}
      {showFinder && (
        <div className="bg-card border border-cyan-500/20 rounded-xl p-4 space-y-4">
          <div className="flex gap-3">
            <input
              type="number"
              placeholder="Governor ID"
              value={govId}
              onChange={(e) => setGovId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !searching && startSearch()}
              disabled={isSearching}
              className="flex-1 px-3 py-2 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-accent/50 disabled:opacity-50"
            />
            <button
              onClick={startSearch}
              disabled={isSearching || !govId}
              className="px-5 py-2 bg-accent text-white rounded-lg text-sm font-medium hover:bg-accent/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {isSearching ? (
                <><span className="animate-spin">⏳</span>Searching...</>
              ) : (
                <>🔍 Find</>
              )}
            </button>
          </div>
          {finderError && <p className="text-red-400 text-sm">{finderError}</p>}

          {isSearching && (
            <div className="flex items-center gap-3 text-sm">
              <div className="animate-spin w-5 h-5 border-2 border-accent border-t-transparent rounded-full" />
              <span className="text-muted">{finderStatus.progress || "Navigating map..."}</span>
            </div>
          )}

          {finderStatus.status === "found" && finderResult && (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 bg-green-500/20 rounded-lg flex items-center justify-center text-lg">📍</div>
                <div>
                  <span className="font-semibold">{finderResult.governor_name}</span>
                  {finderResult.alliance_tag && (
                    <span className="text-muted text-sm ml-2">[{finderResult.alliance_tag}]</span>
                  )}
                  {finderResult.fighting && (
                    <span className="ml-2 px-1.5 py-0.5 bg-red-500/20 text-red-400 text-xs font-bold rounded">IN COMBAT</span>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div className="bg-background p-2.5 rounded-lg">
                  <p className="text-xs text-muted mb-0.5">Coordinates</p>
                  <p className="font-mono font-bold">
                    {finderResult.x > 0 || finderResult.y > 0 ? `${finderResult.x}, ${finderResult.y}` : "Unknown"}
                  </p>
                </div>
                <div className="bg-background p-2.5 rounded-lg">
                  <p className="text-xs text-muted mb-0.5">Shield</p>
                  <p className={`font-bold ${finderResult.shield_remaining_seconds && finderResult.shield_remaining_seconds > 0 ? "text-blue-400" : "text-red-400"}`}>
                    {finderResult.shield_remaining_seconds && finderResult.shield_remaining_seconds > 0
                      ? `🛡️ ${formatShieldTime(finderResult.shield_remaining_seconds)}`
                      : "⚔️ No Shield"}
                  </p>
                </div>
                <div className="bg-background p-2.5 rounded-lg">
                  <p className="text-xs text-muted mb-0.5">Power</p>
                  <p className="font-bold text-yellow-400">{finderResult.power ? finderResult.power.toLocaleString() : "—"}</p>
                </div>
                <div className="bg-background p-2.5 rounded-lg">
                  <p className="text-xs text-muted mb-0.5">Kill Count</p>
                  <p className="font-bold text-red-400">{finderResult.kill ? finderResult.kill.toLocaleString() : "—"}</p>
                </div>
              </div>
              {finderResult.linked_accounts && finderResult.linked_accounts.length > 0 && (
                <div>
                  <p className="text-xs text-muted mb-1">Linked Accounts</p>
                  <div className="flex flex-wrap gap-2">
                    {finderResult.linked_accounts.map((acc, i) => (
                      <span key={i} className="px-2 py-1 bg-background rounded text-xs">
                        {acc.is_main ? "👑 " : "🏠 "}
                        {acc.governor_name || `ID: ${acc.governor_id}`}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {finderStatus.status === "not_found" && (
            <div className="flex items-center gap-2 text-sm text-yellow-400">
              <span>⚠️</span>
              <span>{finderStatus.progress || "Governor not found on the map."}</span>
            </div>
          )}

          {finderStatus.status === "error" && (
            <div className="flex items-center gap-2 text-sm text-red-400">
              <span>❌</span>
              <span>{finderStatus.progress || "Search error occurred."}</span>
            </div>
          )}
        </div>
      )}

      {/* Map + Side Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Canvas */}
        <div className="lg:col-span-2" ref={containerRef}>
          <div className="bg-surface border border-gray-700/50 rounded-lg p-2 relative">
            <canvas
              ref={canvasRef}
              onMouseMove={handleCanvasMove}
              onMouseLeave={() => setHovered(null)}
              className="w-full cursor-crosshair rounded"
              style={{ aspectRatio: "1/1" }}
            />
            {hovered && (
              <div className="absolute top-3 right-3 bg-zinc-900/95 border border-zinc-700 rounded-lg px-3 py-2 text-sm pointer-events-none">
                <div className="font-bold text-white">{hovered.label}</div>
                <div className="text-zinc-400 font-mono text-xs">({hovered.x}, {hovered.y})</div>
                {hovered.extra && <div className="text-zinc-500 text-xs mt-0.5">{hovered.extra}</div>}
              </div>
            )}
            <div className="absolute bottom-3 left-3 flex gap-3 text-xs">
              {Object.entries(COLORS).map(([key, c]) => (
                <span key={key} className="flex items-center gap-1 text-zinc-400">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: c.fill }} />
                  {c.label}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Side panel */}
        <div className="space-y-3 max-h-[600px] overflow-y-auto">
          {/* Shielded players */}
          {data && data.player_locations.filter((p) => p.shield_type).length > 0 && (
            <div className="space-y-1">
              <h4 className="text-xs font-medium text-purple-400 uppercase">🛡 Shielded Players</h4>
              {data.player_locations
                .filter((p) => p.shield_type)
                .slice(0, 20)
                .map((p) => {
                  const shieldLeft = shieldTimeRemaining(p.shield_expires_at);
                  return (
                    <div
                      key={p.governor_id}
                      className="flex items-center justify-between bg-surface border border-gray-700/40 rounded px-2 py-1 text-xs hover:border-purple-500/30"
                      onMouseEnter={() =>
                        setHovered({ type: "players", x: p.x, y: p.y, label: p.governor_name, extra: shieldLeft ? `🛡 ${shieldLeft}` : "🛡 shielded" })
                      }
                      onMouseLeave={() => setHovered(null)}
                    >
                      <div className="truncate">
                        <span className="text-white">{p.governor_name}</span>
                        {p.alliance_tag && <span className="text-zinc-500 ml-1">[{p.alliance_tag}]</span>}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {shieldLeft && <span className="text-blue-400">{shieldLeft}</span>}
                        <span className="text-zinc-500 font-mono">({p.x},{p.y})</span>
                      </div>
                    </div>
                  );
                })}
            </div>
          )}

          {/* All players grouped by alliance */}
          {data && data.player_locations.length > 0 && (
            <div className="space-y-1">
              <h4 className="text-xs font-medium text-blue-400 uppercase">📍 Players ({totalPlayers})</h4>
              {data.player_locations
                .filter((p) => !search || p.governor_name.toLowerCase().includes(search.toLowerCase()))
                .sort((a, b) => (b.power ?? 0) - (a.power ?? 0))
                .slice(0, 50)
                .map((p) => (
                  <div
                    key={p.governor_id}
                    className="flex items-center justify-between bg-surface border border-gray-700/40 rounded px-2 py-1 text-xs hover:border-blue-500/30"
                    onMouseEnter={() =>
                      setHovered({ type: "players", x: p.x, y: p.y, label: p.governor_name, extra: p.power ? formatPower(p.power) : undefined })
                    }
                    onMouseLeave={() => setHovered(null)}
                  >
                    <div className="truncate">
                      <span className="text-white">{p.governor_name}</span>
                      {p.alliance_tag && <span className="text-zinc-500 ml-1">[{p.alliance_tag}]</span>}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {p.power ? <span className="text-yellow-400">{formatPower(p.power)}</span> : null}
                      <span className="text-zinc-500 font-mono">({p.x},{p.y})</span>
                    </div>
                  </div>
                ))}
            </div>
          )}

          {/* Coordinate shares */}
          {data && data.coordinate_shares.length > 0 && (
            <div className="space-y-1">
              <h4 className="text-xs font-medium text-green-400 uppercase">📍 Shared Coords</h4>
              {data.coordinate_shares.slice(0, 30).map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between bg-surface border border-gray-700/40 rounded px-2 py-1 text-xs hover:border-green-500/30"
                  onMouseEnter={() =>
                    setHovered({ type: "coords", x: c.x, y: c.y, label: c.shared_by || "?", extra: c.target_type || undefined })
                  }
                  onMouseLeave={() => setHovered(null)}
                >
                  <div className="truncate">
                    <span className="text-white">{c.shared_by || "?"}</span>
                    {c.target_type && <span className="text-zinc-500 ml-1">({c.target_type})</span>}
                  </div>
                  <div className="flex items-center gap-2 text-zinc-500">
                    <span className="font-mono">({c.x},{c.y})</span>
                    <span>{timeAgo(c.captured_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Chat coordinates */}
          {data && data.chat_coordinates.length > 0 && (
            <div className="space-y-1">
              <h4 className="text-xs font-medium text-amber-400 uppercase">💬 Chat Coords</h4>
              {data.chat_coordinates.slice(0, 30).map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between bg-surface border border-gray-700/40 rounded px-2 py-1 text-xs hover:border-amber-500/30"
                  onMouseEnter={() =>
                    setHovered({ type: "chat", x: c.x, y: c.y, label: c.shared_by || "?", extra: c.text || undefined })
                  }
                  onMouseLeave={() => setHovered(null)}
                >
                  <div className="truncate">
                    <span className="text-white">{c.shared_by || "?"}</span>
                    {c.alliance && <span className="text-zinc-500 ml-1">[{c.alliance}]</span>}
                  </div>
                  <div className="flex items-center gap-2 text-zinc-500">
                    <span className="font-mono">({c.x},{c.y})</span>
                    <span>{timeAgo(c.captured_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {totalPlayers === 0 && totalCoords === 0 && totalChat === 0 && (
            <div className="text-center text-zinc-500 py-8">
              No location data yet. Run a map scan to populate.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
