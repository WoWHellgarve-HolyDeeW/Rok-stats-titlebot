"use client";
import { useState, useEffect, useCallback } from "react";
import { fmt } from "./format";

interface TitleHolder {
  title_id: number;
  title_name: string;
  name: string;
  power: number;
  kills: number;
  id: number;
  castle_level: number;
  server_id: number;
  civilization: number;
  alliance: string;
}

interface AllianceMember {
  name: string;
  power: number;
  kills: number;
  id: number;
  castle_level: number;
  server_id: number;
  civilization: number;
  x: number;
  y: number;
  grade: number;
  title: number;
  is_online: boolean;
  join_time: number;
  login_time: number;
  help_count: number;
  donate_count: number;
}

interface AllianceInfo {
  id: number;
  name: string;
  abbr: string;
  power: number;
  kills: number;
  member_num: number;
  member_max: number;
  territory_count: number;
}

interface PlayerInfo {
  id: number;
  name: string;
  power: number;
  alliance_id: number;
  alliance_name: string;
  server_id: number;
  civilization: number;
  city_hall_level: number;
  vip_level: number;
  vip_exp: number;
  my_title: number;
  troop_power: number;
  building_power: number;
  tech_power: number;
  hero_power: number;
  kill: number;
  dead: number;
  power_peak: number;
  register_time: number;
}

interface KingInfo {
  name: string;
  power: number;
  kills: number;
  id: number;
  alliance: string;
}

type SortKey = "name" | "power" | "kills" | "castle_level" | "is_online" | "help_count" | "donate_count";

const TITLE_EMOJI: Record<string, string> = {
  King: "👑", Queen: "👸", General: "⚔️", "Prime Minister": "📜",
  Justice: "⚖️", Duke: "🏰", Architect: "🔨", Scientist: "🔬",
  Traitor: "🗡️", Beggar: "🪙", Exile: "🚫", Slave: "⛓️", Sluggard: "🐌",
};

const TITLE_ID_TO_NAME: Record<number, string> = {
  1: "King", 2: "Queen", 3: "General", 4: "Prime Minister",
  5: "Justice", 6: "Duke", 7: "Architect", 8: "Scientist",
  9: "Traitor", 10: "Beggar", 11: "Exile", 12: "Slave", 13: "Sluggard",
};

const CIV_NAMES: Record<number, string> = {
  0: "?", 1: "Rome", 2: "Germany", 3: "Britain", 4: "France", 5: "Spain",
  6: "China", 7: "Japan", 8: "Korea", 9: "Arabia", 10: "Ottoman", 11: "Byzantium",
  12: "Viking", 13: "Egypt",
};

const GRADE_NAMES: Record<number, string> = {
  1: "Member", 2: "Officer", 3: "Officer", 4: "R4", 5: "Leader",
};

export default function GameDataPanel({
  kingdom, token, apiUrl, isBotConnected, isTitleBotActive,
}: {
  kingdom: string;
  token: string | null;
  apiUrl: string;
  isBotConnected: boolean;
  isTitleBotActive: boolean;
}) {
  const [titles, setTitles] = useState<TitleHolder[]>([]);
  const [king, setKing] = useState<KingInfo | null>(null);
  const [members, setMembers] = useState<AllianceMember[]>([]);
  const [alliance, setAlliance] = useState<AllianceInfo | null>(null);
  const [player, setPlayer] = useState<PlayerInfo | null>(null);
  const [receivedAt, setReceivedAt] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("power");
  const [sortAsc, setSortAsc] = useState(false);
  const [tab, setTab] = useState<"titles" | "alliance" | "player" | "lookup" | "chat">("titles");
  const [prevReceivedAt, setPrevReceivedAt] = useState<string | null>(null);
  const [lookupQuery, setLookupQuery] = useState("");
  const [lookupResults, setLookupResults] = useState<Array<{
    id: number; name: string; power: number; kills: number;
    kill_score: number; castle_level: number; civilization: number;
    vip_level: number; alliance: string; title: string; source: string;
    is_online: boolean | null; login_time: number;
    x: number; y: number; alliance_grade: number; help_count: number;
  }>>([]);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<Array<{
    id: number; channel: string; nickname: string; alliance_tag: string;
    governor_id: number | null; text: string; captured_at: string;
  }>>([]);

  const fetchGameData = useCallback(async () => {
    try {
      const [titlesRes, membersRes, playerRes] = await Promise.all([
        fetch(`${apiUrl}/kingdoms/${kingdom}/game/titles`),
        fetch(`${apiUrl}/kingdoms/${kingdom}/game/alliance-members`),
        fetch(`${apiUrl}/kingdoms/${kingdom}/game/player-info`),
      ]);
      if (titlesRes.ok) {
        const d = await titlesRes.json();
        setTitles(d.titles || []);
        setKing(d.king || null);
        if (d.received_at) setReceivedAt(d.received_at);
      }
      if (membersRes.ok) {
        const d = await membersRes.json();
        setMembers(d.members || []);
        setAlliance(d.alliance || null);
      }
      if (playerRes.ok) {
        const d = await playerRes.json();
        setPlayer(d.player || null);
      }
    } catch { /* ignore */ }
  }, [apiUrl, kingdom]);

  const handleLookup = useCallback(async () => {
    const q = lookupQuery.trim();
    if (!q) return;
    setLookupLoading(true);
    try {
      const isId = /^\d+$/.test(q);
      const params = isId ? `governor_id=${q}` : `query=${encodeURIComponent(q)}`;
      const res = await fetch(`${apiUrl}/kingdoms/${kingdom}/game/player-lookup?${params}`);
      if (res.ok) {
        const d = await res.json();
        setLookupResults(d.results || []);
      }
    } catch { /* ignore */ }
    finally { setLookupLoading(false); }
  }, [apiUrl, kingdom, lookupQuery]);

  const fetchChatMessages = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/kingdoms/${kingdom}/game/chat-messages?limit=200`);
      if (res.ok) {
        const d = await res.json();
        setChatMessages(d.messages || []);
      }
    } catch { /* ignore */ }
  }, [apiUrl, kingdom]);

  useEffect(() => {
    fetchGameData();
    const interval = setInterval(fetchGameData, 15000);
    return () => clearInterval(interval);
  }, [fetchGameData]);

  // Poll chat messages when on chat tab
  useEffect(() => {
    if (tab !== "chat") return;
    fetchChatMessages();
    const interval = setInterval(fetchChatMessages, 5000);
    return () => clearInterval(interval);
  }, [tab, fetchChatMessages]);

  // When reading, poll faster until new data arrives
  useEffect(() => {
    if (!reading) return;
    const poll = setInterval(async () => {
      await fetchGameData();
    }, 5000);
    return () => clearInterval(poll);
  }, [reading, fetchGameData]);

  // Detect when new snapshot arrives after read request
  useEffect(() => {
    if (reading && receivedAt && prevReceivedAt && receivedAt !== prevReceivedAt) {
      setReading(false);
    }
    setPrevReceivedAt(receivedAt);
  }, [receivedAt, reading, prevReceivedAt]);

  const requestRead = async () => {
    if (!token) return;
    setReading(true);
    try {
      const p = new URLSearchParams({ command: "read_game_data" });
      await fetch(`${apiUrl}/kingdoms/${kingdom}/bot/command?${p}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      // Safety timeout — stop spinner after 90s even if no data arrives
      setTimeout(() => setReading(false), 90000);
    } catch {
      setReading(false);
    }
  };

  const sortedMembers = [...members].sort((a, b) => {
    const va = a[sortKey];
    const vb = b[sortKey];
    if (typeof va === "boolean") return sortAsc ? (va ? 1 : -1) - (vb ? 1 : -1) : (vb ? 1 : -1) - (va ? 1 : -1);
    if (typeof va === "string") return sortAsc ? va.localeCompare(vb as string) : (vb as string).localeCompare(va);
    return sortAsc ? (va as number) - (vb as number) : (vb as number) - (va as number);
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const hasData = titles.length > 0 || members.length > 0 || player;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-card border border-border rounded-xl p-6">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center text-2xl">
              📊
            </div>
            <div>
              <h3 className="text-lg font-semibold">Game Data</h3>
              <p className="text-sm text-muted">
                {receivedAt
                  ? `Snapshot: ${new Date(receivedAt).toLocaleString()}`
                  : "No snapshot yet — click Read to capture"}
              </p>
            </div>
          </div>
          {isBotConnected && token && (
            <button
              onClick={requestRead}
              disabled={reading}
              className="py-2.5 px-5 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-500/50 text-white font-semibold rounded-lg transition-colors flex items-center gap-2 text-sm"
            >
              {reading ? (
                <>
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Reading...
                </>
              ) : "📡 Read Game Data"}
            </button>
          )}
        </div>
        {reading && (
          <div className="mt-3 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
            <div className="flex items-center gap-2 text-sm text-amber-300">
              <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
              <span>Spawning game &amp; reading Lua state... ~30s (game will restart)</span>
            </div>
          </div>
        )}
      </div>

      {!hasData && !reading && (
        <div className="bg-card border border-border rounded-xl p-8 text-center text-muted">
          <p className="text-lg mb-2">No game data yet</p>
          <p className="text-sm">
            {isBotConnected
              ? "Click 'Read Game Data' to capture a snapshot from the game"
              : "Connect the bot first, then read game data"}
          </p>
        </div>
      )}

      {hasData && (
        <>
          {/* Tab selector */}
          <div className="flex gap-1 bg-card border border-border rounded-xl p-1">
            {(["titles", "alliance", "player", "lookup", "chat"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`flex-1 py-2 px-4 rounded-lg text-sm font-medium transition-colors ${
                  tab === t
                    ? "bg-amber-500/15 text-amber-400 border border-amber-500/40"
                    : "hover:bg-zinc-700/30 text-muted"
                }`}
              >
                {t === "titles" ? `👑 Titles (${titles.length})` :
                 t === "alliance" ? `🛡️ Alliance (${members.length})` :
                 t === "player" ? "👤 Player Info" :
                 t === "chat" ? `💬 Chat (${chatMessages.length})` :
                 "🔍 Lookup"}
              </button>
            ))}
          </div>

          {/* TITLES TAB */}
          {tab === "titles" && (
            <div className="space-y-3">
              {king && (
                <div className="bg-card border border-amber-500/30 rounded-xl p-4">
                  <div className="flex items-center gap-3">
                    <span className="text-3xl">👑</span>
                    <div>
                      <p className="text-xs text-amber-400 uppercase tracking-wider">Current King</p>
                      <p className="text-lg font-bold">{king.name} {king.alliance && <span className="text-sm text-muted">[{king.alliance}]</span>}</p>
                      <p className="text-sm text-muted">
                        Power: {fmt(king.power)} · Kills: {fmt(king.kills)}
                      </p>
                    </div>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {titles.map((t) => (
                  <div key={t.title_id} className="bg-card border border-border rounded-xl p-4">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{TITLE_EMOJI[t.title_name] || "🏅"}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <p className="text-xs text-amber-400 uppercase tracking-wider">{t.title_name}</p>
                          <span className="text-xs text-muted">{t.alliance && `[${t.alliance}]`} CH {t.castle_level}</span>
                        </div>
                        <p className="font-semibold truncate">{t.name}</p>
                        <div className="flex gap-4 text-sm text-muted">
                          <span>⚡ {fmt(t.power)}</span>
                          <span>💀 {fmt(t.kills)}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ALLIANCE TAB */}
          {tab === "alliance" && (
            <div className="space-y-3">
              {alliance && (
                <div className="bg-card border border-border rounded-xl p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs text-muted uppercase tracking-wider">Alliance</p>
                      <p className="text-lg font-bold">
                        <span className="text-amber-400">[{alliance.abbr}]</span> {alliance.name}
                      </p>
                    </div>
                    <div className="flex gap-6 text-right text-sm">
                      <div>
                        <p className="text-muted">Members</p>
                        <p className="font-mono font-bold">{alliance.member_num}/{alliance.member_max}</p>
                      </div>
                      <div>
                        <p className="text-muted">Power</p>
                        <p className="font-mono font-bold">{fmt(alliance.power)}</p>
                      </div>
                      <div>
                        <p className="text-muted">Kills</p>
                        <p className="font-mono font-bold">{fmt(alliance.kills)}</p>
                      </div>
                      <div>
                        <p className="text-muted">Territory</p>
                        <p className="font-mono font-bold">{alliance.territory_count}</p>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div className="bg-card border border-border rounded-xl p-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-muted">
                        <th className="pb-2 pr-2 font-medium">#</th>
                        <th className="pb-2 pr-2 font-medium cursor-pointer hover:text-white" onClick={() => handleSort("name")}>
                          Name {sortKey === "name" ? (sortAsc ? "↑" : "↓") : ""}
                        </th>
                        <th className="pb-2 pr-2 font-medium text-right cursor-pointer hover:text-white" onClick={() => handleSort("power")}>
                          Power {sortKey === "power" ? (sortAsc ? "↑" : "↓") : ""}
                        </th>
                        <th className="pb-2 pr-2 font-medium text-right cursor-pointer hover:text-white" onClick={() => handleSort("kills")}>
                          Kills {sortKey === "kills" ? (sortAsc ? "↑" : "↓") : ""}
                        </th>
                        <th className="pb-2 pr-2 font-medium text-right cursor-pointer hover:text-white" onClick={() => handleSort("castle_level")}>
                          CH {sortKey === "castle_level" ? (sortAsc ? "↑" : "↓") : ""}
                        </th>
                        <th className="pb-2 pr-2 font-medium cursor-pointer hover:text-white" onClick={() => handleSort("is_online")}>
                          Status {sortKey === "is_online" ? (sortAsc ? "↑" : "↓") : ""}
                        </th>
                        <th className="pb-2 pr-2 font-medium text-right">Coords</th>
                        <th className="pb-2 font-medium text-right cursor-pointer hover:text-white" onClick={() => handleSort("help_count")}>
                          Helps {sortKey === "help_count" ? (sortAsc ? "↑" : "↓") : ""}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedMembers.map((m, i) => (
                        <tr key={m.id || i} className="border-b border-border/30 hover:bg-zinc-800/30">
                          <td className="py-1.5 pr-2 text-muted font-mono text-xs">{i + 1}</td>
                          <td className="py-1.5 pr-2 font-medium truncate max-w-[180px]">
                            <span className="text-xs text-muted mr-1">{GRADE_NAMES[m.grade] || ""}</span>
                            {m.name}
                          </td>
                          <td className="py-1.5 pr-2 text-right font-mono">{fmt(m.power)}</td>
                          <td className="py-1.5 pr-2 text-right font-mono">{fmt(m.kills)}</td>
                          <td className="py-1.5 pr-2 text-right font-mono">{m.castle_level}</td>
                          <td className="py-1.5 pr-2">
                            {m.is_online ? (
                              <span className="inline-flex items-center gap-1 text-green-400 text-xs">
                                <span className="w-1.5 h-1.5 rounded-full bg-green-400" /> Online
                              </span>
                            ) : (
                              <span className="text-xs text-muted">Offline</span>
                            )}
                          </td>
                          <td className="py-1.5 pr-2 text-right font-mono text-xs text-muted">
                            {m.x},{m.y}
                          </td>
                          <td className="py-1.5 text-right font-mono text-xs">{m.help_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* PLAYER TAB */}
          {tab === "player" && player && (
            <div className="space-y-3">
              {/* Identity */}
              <div className="bg-card border border-border rounded-xl p-6">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">Player</p>
                    <p className="text-lg font-bold">{player.name || "?"}</p>
                    <p className="text-xs text-muted">ID: {player.id}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">Total Power</p>
                    <p className="text-lg font-bold font-mono">{fmt(player.power)}</p>
                    {player.power_peak > 0 && (
                      <p className="text-xs text-muted">Peak: {fmt(player.power_peak)}</p>
                    )}
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">Alliance</p>
                    <p className="text-lg font-bold">{player.alliance_name || "None"}</p>
                    <p className="text-xs text-muted">ID: {player.alliance_id}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">VIP Level</p>
                    <p className="text-lg font-bold font-mono">{player.vip_level || "?"}</p>
                    {player.vip_exp > 0 && (
                      <p className="text-xs text-muted">EXP: {fmt(player.vip_exp)}</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Power Breakdown */}
              {(player.troop_power > 0 || player.building_power > 0 || player.tech_power > 0 || player.hero_power > 0) && (
                <div className="bg-card border border-border rounded-xl p-6">
                  <h4 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Power Breakdown</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <p className="text-xs text-muted">⚔️ Troop Power</p>
                      <p className="text-lg font-bold font-mono">{fmt(player.troop_power)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted">🏗️ Building Power</p>
                      <p className="text-lg font-bold font-mono">{fmt(player.building_power)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted">🔬 Tech Power</p>
                      <p className="text-lg font-bold font-mono">{fmt(player.tech_power)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted">🦸 Hero Power</p>
                      <p className="text-lg font-bold font-mono">{fmt(player.hero_power)}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Combat & Details */}
              <div className="bg-card border border-border rounded-xl p-6">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">💀 Kills</p>
                    <p className="text-lg font-bold font-mono">{fmt(player.kill)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">☠️ Deaths</p>
                    <p className="text-lg font-bold font-mono">{fmt(player.dead)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">City Hall</p>
                    <p className="text-lg font-bold font-mono">Lv. {player.city_hall_level || "?"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">Civilization</p>
                    <p className="text-lg font-bold">{CIV_NAMES[player.civilization] || player.civilization}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">Server</p>
                    <p className="text-lg font-bold font-mono">{player.server_id || "?"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted uppercase tracking-wider">Current Title</p>
                    <p className="text-lg font-bold">
                      {player.my_title ? (TITLE_ID_TO_NAME[player.my_title] || `Title #${player.my_title}`) : "None"}
                    </p>
                  </div>
                  {player.register_time > 0 && (
                    <div>
                      <p className="text-xs text-muted uppercase tracking-wider">Registered</p>
                      <p className="text-lg font-bold">{new Date(player.register_time * 1000).toLocaleDateString()}</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* LOOKUP TAB */}
          {tab === "lookup" && (
            <div className="space-y-3">
              <div className="bg-card border border-border rounded-xl p-4">
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={lookupQuery}
                    onChange={(e) => setLookupQuery(e.target.value)}
                    placeholder="Player name or governor ID..."
                    className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
                    onKeyDown={(e) => e.key === "Enter" && handleLookup()}
                  />
                  <button
                    onClick={handleLookup}
                    disabled={lookupLoading || !lookupQuery.trim()}
                    className="px-4 py-2 bg-accent hover:bg-accent/80 text-bg font-medium rounded-lg transition-colors disabled:opacity-50"
                  >
                    {lookupLoading ? "..." : "Search"}
                  </button>
                </div>
                <p className="text-xs text-muted mt-2">
                  Searches title holders &amp; alliance members from game snapshot data
                </p>
              </div>
              {lookupResults.length > 0 && (
                <div className="space-y-2">
                  {lookupResults.map((r) => {
                    const lastLogin = r.login_time ? new Date(r.login_time).toLocaleString() : null;
                    const gradeLabel = ["", "R1", "R2", "R3", "R4", "Leader"][r.alliance_grade] || "";
                    return (
                    <div key={r.id} className="bg-card border border-border rounded-xl p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="font-semibold">
                            {r.is_online === true && <span className="inline-block w-2 h-2 rounded-full bg-green-400 mr-1.5 align-middle" title="Online" />}
                            {r.is_online === false && <span className="inline-block w-2 h-2 rounded-full bg-zinc-500 mr-1.5 align-middle" title="Offline" />}
                            {r.name}
                            {r.alliance && <span className="text-sm text-muted ml-1">[{r.alliance}]</span>}
                          </p>
                          <p className="text-xs text-muted">
                            ID: {r.id} · CH {r.castle_level} · {CIV_NAMES[r.civilization] || "?"}
                            {gradeLabel && <> · <span className="text-blue-400">{gradeLabel}</span></>}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="font-mono font-bold">⚡ {fmt(r.power)}</p>
                          <p className="text-sm text-muted font-mono">💀 {fmt(r.kills)}</p>
                        </div>
                      </div>
                      {/* Extra info row */}
                      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-muted">
                        {r.kill_score > 0 && <span>Kill Score: <span className="text-foreground font-mono">{fmt(r.kill_score)}</span></span>}
                        {(r.x > 0 || r.y > 0) && <span>Coords: <span className="text-foreground font-mono">X:{Math.round(r.x)} Y:{Math.round(r.y)}</span></span>}
                        {r.help_count > 0 && <span>Helps: <span className="text-foreground font-mono">{r.help_count.toLocaleString()}</span></span>}
                        {lastLogin && <span>Last login: <span className="text-foreground">{lastLogin}</span></span>}
                      </div>
                      {/* Tags row */}
                      <div className="flex gap-2 mt-2">
                        {r.title && <span className="text-xs bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded">{r.title}</span>}
                        {r.is_online === true && <span className="text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded">Online</span>}
                        <span className="text-xs bg-zinc-700 text-zinc-400 px-2 py-0.5 rounded">{r.source.replace(/_/g, " ")}</span>
                      </div>
                    </div>
                    );
                  })}
                </div>
              )}
              {lookupResults.length === 0 && lookupQuery.trim() && !lookupLoading && (
                <div className="text-center py-8 text-muted">
                  <p>No results found</p>
                  <p className="text-sm mt-1">Only players from title holders and alliance members are searchable</p>
                </div>
              )}
            </div>
          )}

          {/* CHAT TAB */}
          {tab === "chat" && (
            <div className="space-y-3">
              <div className="bg-card border border-border rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="font-semibold">Chat Feed</h4>
                    <p className="text-xs text-muted mt-1">
                      Stable queue mode does not depend on live chat capture
                    </p>
                  </div>
                  <span className={`px-3 py-1 rounded-lg text-xs font-medium ${chatMessages.length > 0 ? "bg-amber-500/15 text-amber-300 border border-amber-500/30" : "bg-zinc-800 text-zinc-400 border border-border"}`}>
                    {chatMessages.length > 0 ? "Relay Feed Active" : "External Relay Optional"}
                  </span>
                </div>
                <div className="mt-3 text-sm text-muted">
                  {chatMessages.length > 0
                    ? "Messages below were posted to the API by a separate chat relay process. The queue-only title bot remains isolated from this feed."
                    : "In stable production mode this panel stays empty unless an experimental external chat relay sends messages to the API."}
                </div>
              </div>

              {/* Messages list */}
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                {chatMessages.length > 0 ? (
                  <div className="max-h-[500px] overflow-y-auto">
                    <div className="divide-y divide-border">
                      {chatMessages.map((m) => {
                        const time = m.captured_at ? new Date(m.captured_at).toLocaleTimeString() : "";
                        const isTitleReq = m.text && /\b(scientist|science|architect|duke|justice|duque|archi|build|cient|justica)\b/i.test(m.text);
                        return (
                          <div key={m.id} className={`px-4 py-2.5 ${isTitleReq ? "bg-amber-500/5 border-l-2 border-l-amber-500" : ""}`}>
                            <div className="flex items-center gap-2 text-xs text-muted">
                              <span className="bg-zinc-700 px-1.5 py-0.5 rounded text-zinc-400">
                                {m.channel === "kingdom" ? "Kingdom" : m.channel === "returning" ? "Returning" : m.channel === "recruitment" ? "Recruitment" : m.channel === "alliance" ? "Alliance" : m.channel === "dm" ? "DM" : m.channel === "6" ? "Alliance" : m.channel === "4" ? "World" : m.channel === "25" ? "Language" : m.channel || "Unknown"}
                              </span>
                              {m.alliance_tag && <span className="text-blue-400">[{m.alliance_tag}]</span>}
                              <span className="font-medium text-foreground">{m.nickname || "Unknown"}</span>
                              <span className="ml-auto">{time}</span>
                            </div>
                            <p className="text-sm mt-0.5">
                              {m.text}
                              {isTitleReq && <span className="ml-2 text-xs bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded">Title Request</span>}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-12 text-muted">
                    <p className="text-3xl mb-2">💬</p>
                    <p>No chat messages received yet</p>
                    <p className="text-sm mt-1">Queue-only production mode does not capture live chat. Enable the experimental external relay to populate this feed.</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
