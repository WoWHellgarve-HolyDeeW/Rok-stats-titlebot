"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback, useRef } from "react";

interface ChatEntry {
  id: number;
  nickname: string;
  alliance_tag: string | null;
  governor_id: number | null;
  location: string;
  kvk_side: string | null;
  server_id: number | null;
  text: string | null;
  captured_at: string;
}

interface CoordEntry {
  id: number;
  x: number;
  y: number;
  shared_by: string | null;
  target_type: string | null;
  location: string | null;
  captured_at: string;
}

interface PlayerEntry {
  id: number;
  governor_id: number;
  nickname: string;
  alliance_tag: string | null;
  power: number | null;
  kill_points: number | null;
  vip_level: number | null;
  city_hall_level: number | null;
  dead: number | null;
  t4_kills: number | null;
  t5_kills: number | null;
  is_online: boolean | null;
  location: string | null;
  captured_at: string;
}

interface ActiveSession {
  session_id: string;
  started_at: string;
  chat_count: number;
  player_count: number;
  coord_count: number;
}

interface ActivityStats {
  total_chats: number;
  kd_chats: number;
  lk_chats: number;
  unique_players: number;
  coordinates: number;
  player_sightings: number;
}

interface ActivityData {
  active_session: ActiveSession | null;
  stats: ActivityStats;
  chat_feed: ChatEntry[];
  coordinates: CoordEntry[];
  players: PlayerEntry[];
}

interface ChatStats {
  period_hours: number;
  total_messages: number;
  top_chatters: { nickname: string; alliance: string | null; count: number; kd: number; lk: number }[];
  hourly_activity: { hour: number; kd: number; lk: number }[];
  top_alliances: { tag: string; count: number }[];
}

type TabId = "feed" | "stats" | "coords" | "players";
type WsStatus = "disconnected" | "connecting" | "connected" | "error";

export default function LiveActivityPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const [data, setData] = useState<ActivityData | null>(null);
  const [chatStats, setChatStats] = useState<ChatStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId>("feed");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [minutesWindow, setMinutesWindow] = useState(60);
  const [wsStatus, setWsStatus] = useState<WsStatus>("disconnected");
  const [wsEvents, setWsEvents] = useState(0);
  const [chatFilter, setChatFilter] = useState<string>("ALL");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  /* ═══ WebSocket connection ═══ */
  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setWsStatus("connecting");
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const host = apiBase.startsWith("http")
      ? new URL(apiBase).host
      : window.location.host;
    const wsUrl = `${proto}://${host}/api/ws/live/${kdNum}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setWsStatus("connected");

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "chat") {
          setData((prev) => {
            if (!prev) return prev;
            const exists = prev.chat_feed.some((c) => c.id === msg.data.id);
            if (exists) return prev;
            return {
              ...prev,
              chat_feed: [msg.data, ...prev.chat_feed].slice(0, 500),
              stats: { ...prev.stats, total_chats: prev.stats.total_chats + 1 },
            };
          });
          setWsEvents((n) => n + 1);
        } else if (msg.type === "coordinate") {
          setData((prev) => {
            if (!prev) return prev;
            const exists = prev.coordinates.some((c) => c.id === msg.data.id);
            if (exists) return prev;
            return {
              ...prev,
              coordinates: [msg.data, ...prev.coordinates].slice(0, 500),
              stats: { ...prev.stats, coordinates: prev.stats.coordinates + 1 },
            };
          });
          setWsEvents((n) => n + 1);
        } else if (msg.type === "player") {
          setData((prev) => {
            if (!prev) return prev;
            const exists = prev.players.some((p) => p.id === msg.data.id);
            if (exists) return prev;
            return {
              ...prev,
              players: [msg.data, ...prev.players].slice(0, 500),
              stats: { ...prev.stats, player_sightings: prev.stats.player_sightings + 1 },
            };
          });
          setWsEvents((n) => n + 1);
        }
      } catch { /* ignore parse errors */ }
    };

    ws.onerror = () => setWsStatus("error");

    ws.onclose = () => {
      setWsStatus("disconnected");
      wsRef.current = null;
      // Auto-reconnect after 5s
      if (autoRefresh) {
        reconnectTimer.current = setTimeout(connectWs, 5000);
      }
    };
  }, [apiBase, kdNum, autoRefresh]);

  // Connect WS on mount, disconnect on unmount
  useEffect(() => {
    connectWs();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connectWs]);

  // Close WS when autoRefresh is disabled
  useEffect(() => {
    if (!autoRefresh) {
      wsRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    } else if (wsRef.current?.readyState !== WebSocket.OPEN) {
      connectWs();
    }
  }, [autoRefresh, connectWs]);

  const fetchActivity = useCallback(async () => {
    try {
      const res = await fetch(
        `${apiBase}/kingdoms/${kdNum}/live/activity?minutes=${minutesWindow}&limit=200`
      );
      if (res.ok) setData(await res.json());
    } catch (err) {
      console.error("Failed to fetch live activity:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBase, kdNum, minutesWindow]);

  const fetchChatStats = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/live/chat-stats?hours=24`);
      if (res.ok) setChatStats(await res.json());
    } catch (err) {
      console.error("Failed to fetch chat stats:", err);
    }
  }, [apiBase, kdNum]);

  useEffect(() => {
    fetchActivity();
    fetchChatStats();
    if (!autoRefresh) return;
    // Polling fallback — only active when WS is not connected
    const interval = setInterval(() => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        fetchActivity();
      }
      fetchChatStats(); // stats always polled (no WS equivalent)
    }, 10000);
    return () => clearInterval(interval);
  }, [fetchActivity, fetchChatStats, autoRefresh]);

  const timeAgo = (iso: string) => {
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    return `${Math.round(diff / 3600)}h ago`;
  };

  const locationBadge = (loc: string | null) => {
    if (!loc) return null;
    const colors: Record<string, string> = {
      KD: "bg-blue-500/20 text-blue-400 border-blue-500/30",
      LK: "bg-red-500/20 text-red-400 border-red-500/30",
      LK_CROSS: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    };
    return (
      <span className={`px-1.5 py-0.5 rounded text-xs font-mono border ${colors[loc] || "bg-gray-600/20 text-gray-400 border-gray-600/30"}`}>
        {loc}
      </span>
    );
  };

  const formatPower = (n: number | null) => {
    if (n == null) return "—";
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return n.toString();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-accent"></div>
      </div>
    );
  }

  const stats = data?.stats;
  const session = data?.active_session;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <svg className="w-6 h-6 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          Live Activity
        </h1>
        <div className="flex items-center gap-3">
          <select
            className="bg-surface border border-gray-700 rounded px-2 py-1 text-sm"
            value={minutesWindow}
            onChange={(e) => setMinutesWindow(parseInt(e.target.value))}
          >
            <option value={15}>Last 15 min</option>
            <option value={30}>Last 30 min</option>
            <option value={60}>Last 1 hour</option>
            <option value={180}>Last 3 hours</option>
            <option value={720}>Last 12 hours</option>
            <option value={1440}>Last 24 hours</option>
          </select>
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-sm font-medium transition-colors ${
              autoRefresh
                ? "bg-green-500/20 text-green-400 border border-green-500/30"
                : "bg-gray-700/50 text-gray-400 border border-gray-600"
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${autoRefresh ? "bg-green-400 animate-pulse" : "bg-gray-500"}`} />
            {autoRefresh ? "Live" : "Paused"}
          </button>
        </div>
      </div>

      {/* WebSocket status bar */}
      <div className={`flex items-center justify-between rounded-lg px-3 py-1.5 text-xs border ${
        wsStatus === "connected"
          ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
          : wsStatus === "connecting"
          ? "bg-yellow-500/10 border-yellow-500/30 text-yellow-400"
          : wsStatus === "error"
          ? "bg-red-500/10 border-red-500/30 text-red-400"
          : "bg-zinc-700/30 border-zinc-600/30 text-zinc-400"
      }`}>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${
            wsStatus === "connected" ? "bg-emerald-400 animate-pulse"
            : wsStatus === "connecting" ? "bg-yellow-400 animate-pulse"
            : wsStatus === "error" ? "bg-red-400"
            : "bg-zinc-500"
          }`} />
          {wsStatus === "connected" && `WebSocket connected — ${wsEvents} events received`}
          {wsStatus === "connecting" && "Connecting WebSocket…"}
          {wsStatus === "error" && "WebSocket error — falling back to polling"}
          {wsStatus === "disconnected" && (autoRefresh ? "WebSocket disconnected — reconnecting…" : "WebSocket disconnected")}
        </div>
        {wsStatus !== "connected" && autoRefresh && (
          <button
            onClick={connectWs}
            className="text-xs text-blue-400 hover:underline"
          >
            Reconnect
          </button>
        )}
      </div>

      {/* Session banner */}
      {session ? (
        <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-green-400 animate-pulse" />
            <span className="text-green-400 font-medium text-sm">Frida session active</span>
            <span className="text-gray-400 text-xs">since {new Date(session.started_at).toLocaleTimeString()}</span>
          </div>
          <div className="flex gap-4 text-xs text-gray-400">
            <span>{session.chat_count} chats</span>
            <span>{session.player_count} players</span>
            <span>{session.coord_count} coords</span>
          </div>
        </div>
      ) : (
        <div className="bg-gray-700/30 border border-gray-600/30 rounded-lg p-3 flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-gray-500" />
          <span className="text-gray-400 text-sm">No active Frida session — showing historical data</span>
        </div>
      )}

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label: "Total Chats", value: stats.total_chats, color: "text-white" },
            { label: "KD Chat", value: stats.kd_chats, color: "text-blue-400" },
            { label: "LK Chat", value: stats.lk_chats, color: "text-red-400" },
            { label: "Unique Players", value: stats.unique_players, color: "text-amber-400" },
            { label: "Coordinates", value: stats.coordinates, color: "text-green-400" },
            { label: "Player Sightings", value: stats.player_sightings, color: "text-purple-400" },
          ].map((s) => (
            <div key={s.label} className="bg-surface border border-gray-700/50 rounded-lg p-3 text-center">
              <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
              <div className="text-xs text-gray-400 mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-gray-700">
        {(
          [
            { id: "feed" as TabId, label: "Chat Feed", count: data?.chat_feed.length },
            { id: "stats" as TabId, label: "Chat Stats", count: chatStats?.total_messages },
            { id: "coords" as TabId, label: "Coordinates", count: data?.coordinates.length },
            { id: "players" as TabId, label: "Players", count: data?.players.length },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-accent text-accent"
                : "border-transparent text-gray-400 hover:text-gray-300"
            }`}
          >
            {tab.label}
            {tab.count != null && tab.count > 0 && (
              <span className="ml-1.5 text-xs bg-gray-700/60 px-1.5 py-0.5 rounded">{tab.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="min-h-[400px]">
        {/* ── Chat Feed ── */}
        {activeTab === "feed" && (
          <div className="space-y-1">
            {/* Chat location filter */}
            <div className="flex items-center gap-2 mb-3 pb-2 border-b border-gray-700/50">
              <span className="text-xs text-gray-500 mr-1">Filter:</span>
              {["ALL", "KD", "LK", "LK_CROSS"].map((loc) => {
                const colors: Record<string, string> = {
                  ALL: chatFilter === "ALL" ? "bg-accent/20 text-accent border-accent/40" : "bg-gray-700/40 text-gray-400 border-gray-600/50 hover:bg-gray-600/40",
                  KD: chatFilter === "KD" ? "bg-blue-500/20 text-blue-400 border-blue-500/40" : "bg-gray-700/40 text-gray-400 border-gray-600/50 hover:bg-gray-600/40",
                  LK: chatFilter === "LK" ? "bg-red-500/20 text-red-400 border-red-500/40" : "bg-gray-700/40 text-gray-400 border-gray-600/50 hover:bg-gray-600/40",
                  LK_CROSS: chatFilter === "LK_CROSS" ? "bg-orange-500/20 text-orange-400 border-orange-500/40" : "bg-gray-700/40 text-gray-400 border-gray-600/50 hover:bg-gray-600/40",
                };
                const count = loc === "ALL"
                  ? data?.chat_feed.length ?? 0
                  : data?.chat_feed.filter((c) => c.location === loc).length ?? 0;
                return (
                  <button
                    key={loc}
                    onClick={() => setChatFilter(loc)}
                    className={`px-2.5 py-1 rounded text-xs font-medium border transition-colors ${colors[loc]}`}
                  >
                    {loc === "LK_CROSS" ? "LK Cross" : loc} ({count})
                  </button>
                );
              })}
            </div>
            {(() => {
              const filtered = chatFilter === "ALL"
                ? data?.chat_feed ?? []
                : data?.chat_feed.filter((c) => c.location === chatFilter) ?? [];
              if (filtered.length === 0) {
                return <div className="text-center text-gray-500 py-12">No chat activity for this filter</div>;
              }
              return filtered.map((c) => (
              <div
                key={c.id}
                className="flex items-center gap-2 px-3 py-1.5 rounded hover:bg-surface/60 text-sm group"
              >
                <span className="text-gray-500 text-xs w-16 shrink-0 text-right font-mono">
                  {timeAgo(c.captured_at)}
                </span>
                {locationBadge(c.location)}
                {c.alliance_tag && (
                  <span className="text-gray-400 font-mono text-xs">[{c.alliance_tag}]</span>
                )}
                <span className="text-white font-medium truncate max-w-[200px]">{c.nickname || "—"}</span>
                {c.governor_id && (
                  <span className="text-gray-600 text-xs font-mono">#{c.governor_id}</span>
                )}
                {c.text && (
                  <span className="text-gray-500 truncate flex-1">{c.text}</span>
                )}
                {c.kvk_side && (
                  <span className="text-xs text-gray-600 ml-auto">side {c.kvk_side}</span>
                )}
              </div>
            ));
            })()}
          </div>
        )}

        {/* ── Chat Stats ── */}
        {activeTab === "stats" && chatStats && (
          <div className="space-y-6">
            {/* Top Chatters */}
            <div>
              <h3 className="text-sm font-semibold text-gray-300 mb-2">Top Chatters (24h)</h3>
              <div className="bg-surface rounded-lg border border-gray-700/50 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700/50 text-gray-400 text-xs">
                      <th className="text-left px-3 py-2">#</th>
                      <th className="text-left px-3 py-2">Player</th>
                      <th className="text-left px-3 py-2">Alliance</th>
                      <th className="text-right px-3 py-2">KD</th>
                      <th className="text-right px-3 py-2">LK</th>
                      <th className="text-right px-3 py-2">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chatStats.top_chatters.map((c, i) => (
                      <tr key={c.nickname} className="border-b border-gray-700/20 hover:bg-gray-700/20">
                        <td className="px-3 py-1.5 text-gray-500">{i + 1}</td>
                        <td className="px-3 py-1.5 text-white font-medium">{c.nickname}</td>
                        <td className="px-3 py-1.5 text-gray-400 font-mono text-xs">
                          {c.alliance ? `[${c.alliance}]` : "—"}
                        </td>
                        <td className="px-3 py-1.5 text-right text-blue-400">{c.kd}</td>
                        <td className="px-3 py-1.5 text-right text-red-400">{c.lk}</td>
                        <td className="px-3 py-1.5 text-right font-bold">{c.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {chatStats.top_chatters.length === 0 && (
                  <div className="text-center text-gray-500 py-6">No data yet</div>
                )}
              </div>
            </div>

            {/* Hourly Activity Chart (simple bar) */}
            <div>
              <h3 className="text-sm font-semibold text-gray-300 mb-2">Hourly Activity (24h)</h3>
              <div className="bg-surface rounded-lg border border-gray-700/50 p-4">
                {chatStats.hourly_activity.length > 0 ? (
                  <div className="flex items-end gap-1 h-32">
                    {Array.from({ length: 24 }, (_, h) => {
                      const entry = chatStats.hourly_activity.find((e) => e.hour === h);
                      const kd = entry?.kd || 0;
                      const lk = entry?.lk || 0;
                      const total = kd + lk;
                      const maxVal = Math.max(...chatStats.hourly_activity.map((e) => e.kd + e.lk), 1);
                      const pct = (total / maxVal) * 100;
                      return (
                        <div key={h} className="flex-1 flex flex-col items-center gap-0.5">
                          <div className="w-full flex flex-col justify-end" style={{ height: "100px" }}>
                            <div
                              className="w-full rounded-t"
                              style={{
                                height: `${pct}%`,
                                background: `linear-gradient(to top, rgb(59 130 246 / 0.6) ${
                                  total > 0 ? (kd / total) * 100 : 50
                                }%, rgb(239 68 68 / 0.6) 100%)`,
                                minHeight: total > 0 ? "2px" : "0",
                              }}
                              title={`${h}:00 — KD: ${kd}, LK: ${lk}`}
                            />
                          </div>
                          <span className="text-[10px] text-gray-500">{h}</span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-center text-gray-500 py-6">No hourly data</div>
                )}
                <div className="flex justify-center gap-4 mt-3 text-xs">
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-2 rounded bg-blue-500/60" /> KD
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-2 rounded bg-red-500/60" /> LK
                  </span>
                </div>
              </div>
            </div>

            {/* Top Alliances */}
            <div>
              <h3 className="text-sm font-semibold text-gray-300 mb-2">Most Active Alliances (24h)</h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {chatStats.top_alliances.map((a) => (
                  <div
                    key={a.tag}
                    className="bg-surface border border-gray-700/50 rounded-lg p-3 text-center"
                  >
                    <div className="text-white font-mono font-bold">[{a.tag}]</div>
                    <div className="text-xs text-gray-400 mt-0.5">{a.count} messages</div>
                  </div>
                ))}
                {chatStats.top_alliances.length === 0 && (
                  <div className="col-span-full text-center text-gray-500 py-4">No alliance data</div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Coordinates ── */}
        {activeTab === "coords" && (
          <div>
            {data?.coordinates.length === 0 && (
              <div className="text-center text-gray-500 py-12">No coordinates captured in this time window</div>
            )}
            <div className="grid gap-2">
              {data?.coordinates.map((co) => (
                <div
                  key={co.id}
                  className="flex items-center gap-3 bg-surface border border-gray-700/50 rounded-lg px-4 py-2"
                >
                  <div className="text-green-400 font-mono font-bold text-lg">
                    ({co.x}, {co.y})
                  </div>
                  <div className="flex flex-col">
                    {co.shared_by && (
                      <span className="text-sm text-white">{co.shared_by}</span>
                    )}
                    <span className="text-xs text-gray-500">
                      {co.target_type || "coordinate"} · {timeAgo(co.captured_at)}
                    </span>
                  </div>
                  {locationBadge(co.location)}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Players ── */}
        {activeTab === "players" && (
          <div>
            {data?.players.length === 0 && (
              <div className="text-center text-gray-500 py-12">No player sightings in this time window</div>
            )}
            <div className="bg-surface rounded-lg border border-gray-700/50 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700/50 text-gray-400 text-xs">
                    <th className="text-left px-3 py-2">Player</th>
                    <th className="text-left px-3 py-2">Alliance</th>
                    <th className="text-right px-3 py-2">Power</th>
                    <th className="text-center px-3 py-2">CH</th>
                    <th className="text-center px-3 py-2">VIP</th>
                    <th className="text-right px-3 py-2">Kill Pts</th>
                    <th className="text-right px-3 py-2">T4 Kills</th>
                    <th className="text-right px-3 py-2">T5 Kills</th>
                    <th className="text-right px-3 py-2">Dead</th>
                    <th className="text-center px-3 py-2">Online</th>
                    <th className="text-right px-3 py-2">Seen</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.players.map((p) => (
                    <tr key={p.id} className="border-b border-gray-700/20 hover:bg-gray-700/20">
                      <td className="px-3 py-1.5">
                        <div className="text-white font-medium">{p.nickname}</div>
                        <div className="text-xs text-gray-500">ID: {p.governor_id}</div>
                      </td>
                      <td className="px-3 py-1.5 text-gray-400 font-mono text-xs">
                        {p.alliance_tag ? `[${p.alliance_tag}]` : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right text-amber-400">{formatPower(p.power)}</td>
                      <td className="px-3 py-1.5 text-center">
                        {p.city_hall_level != null ? (
                          <span className="text-purple-400">{p.city_hall_level}</span>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        {p.vip_level != null ? (
                          <span className="text-yellow-400">{p.vip_level}</span>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right text-red-400">{formatPower(p.kill_points)}</td>
                      <td className="px-3 py-1.5 text-right text-orange-400">{p.t4_kills != null ? formatPower(p.t4_kills) : "—"}</td>
                      <td className="px-3 py-1.5 text-right text-red-500">{p.t5_kills != null ? formatPower(p.t5_kills) : "—"}</td>
                      <td className="px-3 py-1.5 text-right text-gray-400">{p.dead != null ? formatPower(p.dead) : "—"}</td>
                      <td className="px-3 py-1.5 text-center">
                        {p.is_online === true && <span className="text-green-400">●</span>}
                        {p.is_online === false && <span className="text-gray-500">○</span>}
                        {p.is_online == null && "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right text-xs text-gray-500">
                        {timeAgo(p.captured_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
