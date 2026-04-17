"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback, useRef } from "react";

interface PlayerLoc {
  governor_id: number;
  governor_name: string;
  x: number;
  y: number;
  shield_type: string | null;
  shield_expires_at: string | null;
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

type LayerKey = "players" | "coords" | "chat";

const COLORS = {
  players: { fill: "#3b82f6", ring: "#60a5fa", label: "Players" },
  coords: { fill: "#22c55e", ring: "#4ade80", label: "Coord Shares" },
  chat: { fill: "#f59e0b", ring: "#fbbf24", label: "Chat Coords" },
  shielded: { fill: "#a855f7", ring: "#c084fc", label: "Shielded" },
};

const MAP_SIZE = 1200; // RoK maps are ~1200x1200

export default function MapPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
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

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const fetchMap = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/map/locations`);
      if (res.ok) setData(await res.json());
    } catch (err) {
      console.error("Failed to fetch map:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBase, kdNum]);

  useEffect(() => {
    fetchMap();
  }, [fetchMap]);

  const toggleLayer = (key: LayerKey) =>
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));

  // Collect all points for rendering
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
        pts.push({
          x: p.x,
          y: p.y,
          type: "players",
          label: p.governor_name,
          extra: p.shield_type ? `🛡 ${p.shield_type}` : undefined,
          shielded: !!p.shield_type,
        });
      }
    }

    if (layers.coords) {
      for (const c of data.coordinate_shares) {
        pts.push({
          x: c.x,
          y: c.y,
          type: "coords",
          label: c.shared_by || "Unknown",
          extra: c.target_type || undefined,
        });
      }
    }

    if (layers.chat) {
      for (const c of data.chat_coordinates) {
        if (search && !(c.shared_by || "").toLowerCase().includes(search.toLowerCase())) continue;
        pts.push({
          x: c.x,
          y: c.y,
          type: "chat",
          label: c.shared_by || "Unknown",
          extra: c.text || undefined,
        });
      }
    }

    return pts;
  }, [data, layers, search]);

  // Canvas drawing
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

    // Background
    ctx.fillStyle = "#0a0a0f";
    ctx.fillRect(0, 0, size, size);

    // Grid lines
    ctx.strokeStyle = "#1e1e2e";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= MAP_SIZE; i += 100) {
      const p = i * scale;
      ctx.beginPath();
      ctx.moveTo(p, 0);
      ctx.lineTo(p, size);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, p);
      ctx.lineTo(size, p);
      ctx.stroke();
    }

    // Grid labels
    ctx.fillStyle = "#3f3f46";
    ctx.font = "9px monospace";
    for (let i = 0; i <= MAP_SIZE; i += 200) {
      ctx.fillText(String(i), i * scale + 2, 10);
      ctx.fillText(String(i), 2, i * scale + 10);
    }

    // Draw points
    const points = getPoints();
    for (const pt of points) {
      const px = pt.x * scale;
      const py = pt.y * scale;
      const color = pt.shielded ? COLORS.shielded : COLORS[pt.type];

      // Outer glow
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fillStyle = color.ring + "40";
      ctx.fill();

      // Inner dot
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fillStyle = color.fill;
      ctx.fill();
    }

    // Highlighted point label
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

  // Canvas hover detection
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
        if (dist < closestDist) {
          closestDist = dist;
          closest = pt;
        }
      }

      if (closest) {
        setHovered({
          type: closest.type,
          x: closest.x,
          y: closest.y,
          label: closest.label,
          extra: closest.extra,
        });
      } else {
        setHovered(null);
      }
    },
    [getPoints]
  );

  const timeAgo = (iso: string) => {
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-accent" />
      </div>
    );
  }

  const points = getPoints();
  const totalPlayers = data?.player_locations.length ?? 0;
  const totalCoords = data?.coordinate_shares.length ?? 0;
  const totalChat = data?.chat_coordinates.length ?? 0;
  const shielded = data?.player_locations.filter((p) => p.shield_type).length ?? 0;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          🗺️ Kingdom Map
        </h1>
        <button
          onClick={fetchMap}
          className="px-3 py-1 text-sm rounded bg-zinc-700 hover:bg-zinc-600 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Stats */}
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
        {(["players", "coords", "chat"] as LayerKey[]).map((key) => (
          <button
            key={key}
            onClick={() => toggleLayer(key)}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-sm border transition-colors ${
              layers[key]
                ? `border-${key === "players" ? "blue" : key === "coords" ? "green" : "amber"}-500/40 bg-${key === "players" ? "blue" : key === "coords" ? "green" : "amber"}-500/10 text-${key === "players" ? "blue" : key === "coords" ? "green" : "amber"}-400`
                : "border-zinc-700 bg-zinc-800/50 text-zinc-500"
            }`}
          >
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: layers[key] ? COLORS[key].fill : "#52525b" }}
            />
            {COLORS[key].label}
          </button>
        ))}
        <span className="text-sm text-zinc-500 ml-auto">
          {points.length} points visible
        </span>
      </div>

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
            {/* Hover tooltip */}
            {hovered && (
              <div className="absolute top-3 right-3 bg-zinc-900/95 border border-zinc-700 rounded-lg px-3 py-2 text-sm pointer-events-none">
                <div className="font-bold text-white">{hovered.label}</div>
                <div className="text-zinc-400 font-mono text-xs">
                  ({hovered.x}, {hovered.y})
                </div>
                {hovered.extra && (
                  <div className="text-zinc-500 text-xs mt-0.5">{hovered.extra}</div>
                )}
              </div>
            )}
            {/* Legend */}
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

        {/* Side panel — recent coordinates list */}
        <div className="space-y-3 max-h-[600px] overflow-y-auto">
          <h3 className="text-sm font-semibold text-zinc-300">Recent Coordinates</h3>

          {/* Shielded players */}
          {data && data.player_locations.filter((p) => p.shield_type).length > 0 && (
            <div className="space-y-1">
              <h4 className="text-xs font-medium text-purple-400 uppercase">🛡 Shielded Players</h4>
              {data.player_locations
                .filter((p) => p.shield_type)
                .slice(0, 20)
                .map((p) => (
                  <div
                    key={p.governor_id}
                    className="flex items-center justify-between bg-surface border border-gray-700/40 rounded px-2 py-1 text-xs hover:border-purple-500/30"
                    onMouseEnter={() =>
                      setHovered({ type: "players", x: p.x, y: p.y, label: p.governor_name, extra: `🛡 ${p.shield_type}` })
                    }
                    onMouseLeave={() => setHovered(null)}
                  >
                    <span className="text-white truncate">{p.governor_name}</span>
                    <span className="text-zinc-500 font-mono">
                      ({p.x},{p.y})
                    </span>
                  </div>
                ))}
            </div>
          )}

          {/* Coordinate shares */}
          {data && data.coordinate_shares.length > 0 && (
            <div className="space-y-1">
              <h4 className="text-xs font-medium text-green-400 uppercase">📍 Shared Coordinates</h4>
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
                    <span className="font-mono">
                      ({c.x},{c.y})
                    </span>
                    <span>{timeAgo(c.captured_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Chat coordinates */}
          {data && data.chat_coordinates.length > 0 && (
            <div className="space-y-1">
              <h4 className="text-xs font-medium text-amber-400 uppercase">💬 Chat Coordinates</h4>
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
                    <span className="font-mono">
                      ({c.x},{c.y})
                    </span>
                    <span>{timeAgo(c.captured_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {totalPlayers === 0 && totalCoords === 0 && totalChat === 0 && (
            <div className="text-center text-zinc-500 py-8">
              No location data available yet. Start a Frida session to capture coordinates.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
