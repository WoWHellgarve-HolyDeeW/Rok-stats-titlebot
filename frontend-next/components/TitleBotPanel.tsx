"use client";
import { useState, useEffect, useCallback } from "react";

type TitleType = "scientist" | "architect" | "duke" | "justice";

interface TitleRequest {
  id: number;
  governor_id: number;
  governor_name: string;
  alliance_tag: string | null;
  title_type: string;
  duration_hours: number;
  status: string;
  priority: number;
  created_at: string;
  assigned_at: string | null;
  bot_message: string | null;
}

interface TitleStats {
  pending: number;
  assigned: number;
  completed_today: number;
  queue_position_estimate_minutes: number;
}

interface TitleHoldStatus {
  title_type: TitleType;
  hold_minutes: number;
  state: "available" | "in_progress" | "cooldown" | string;
  available_at: string | null;
  current_holder_governor_id: number | null;
  current_holder_name: string | null;
}

interface TitleBotSettingsData {
  bot_alliance_tag: string | null;
  bot_alliance_name: string | null;
  enable_scientist: boolean;
  enable_duke: boolean;
  enable_architect: boolean;
  enable_justice: boolean;
  scientist_hold_minutes: number;
  duke_hold_minutes: number;
  architect_hold_minutes: number;
  justice_hold_minutes: number;
  hold_statuses: TitleHoldStatus[];
}

interface ChatMessage {
  id: number;
  channel: string | null;
  nickname: string | null;
  alliance_tag: string | null;
  governor_id: number | null;
  text: string;
  captured_at: string | null;
}

type LiveChatChannel = "dm" | "kingdom" | "alliance";

interface LiveChatMessage extends ChatMessage {
  liveChannel: LiveChatChannel;
}

const DEFAULT_HOLD_MINUTES = 5;

const TITLE_INFO: Record<TitleType, { name: string; buff: string; icon: string }> = {
  scientist: { name: "Scientist", buff: "+5% Research Speed", icon: "🔬" },
  architect: { name: "Architect", buff: "+5% Building Speed", icon: "🏗️" },
  duke: { name: "Duke", buff: "+10% Gathering Speed", icon: "⚒️" },
  justice: { name: "Justice", buff: "+5% Troop Attack", icon: "⚔️" },
};

const TITLE_SETTINGS_ORDER: TitleType[] = ["scientist", "duke", "architect", "justice"];

const HOLD_STATUS_STYLES: Record<string, string> = {
  available: "border-green-500/30 bg-green-500/5",
  in_progress: "border-blue-500/30 bg-blue-500/5",
  cooldown: "border-amber-500/30 bg-amber-500/5",
};

const LIVE_CHAT_REQUEST_PATTERN = /\b(scientist|science|architect|duke|justice|duque|archi|build|cient|justica)\b/i;

const LIVE_CHAT_SECTION_TITLES: Record<LiveChatChannel, string> = {
  dm: "DM",
  kingdom: "Kingdom",
  alliance: "Alliance",
};

const LIVE_CHAT_SECTION_ORDER: LiveChatChannel[] = ["dm", "kingdom", "alliance"];

function getTitleInfo(titleType: string) {
  return Object.prototype.hasOwnProperty.call(TITLE_INFO, titleType)
    ? TITLE_INFO[titleType as TitleType]
    : null;
}

function normalizeLiveChatChannel(channel: string | null): LiveChatChannel | null {
  switch (channel) {
    case "dm":
      return "dm";
    case "kingdom":
      return "kingdom";
    case "alliance":
    case "6":
      return "alliance";
    default:
      return null;
  }
}

function getChatChannelLabel(channel: string | null) {
  switch (channel) {
    case "kingdom":
      return "Kingdom";
    case "returning":
      return "Returning";
    case "recruitment":
      return "Recruitment";
    case "alliance":
    case "6":
      return "Alliance";
    case "dm":
      return "DM";
    case "4":
      return "World";
    case "25":
      return "Language";
    default:
      return channel || "Unknown";
  }
}

function sanitizeHoldMinutes(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1440, Math.round(value)));
}

function formatAvailabilityTime(value: string | null) {
  if (!value) return "soon";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "soon";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function TitleBotPanel({
  kingdom,
  token,
  apiUrl,
  isBotConnected,
  isTitleBotActive,
  onToggleTitleBot,
  togglingTitleBot,
}: {
  kingdom: string;
  token: string | null;
  apiUrl: string;
  isBotConnected: boolean;
  isTitleBotActive: boolean;
  onToggleTitleBot: () => void;
  togglingTitleBot: boolean;
}) {
  const [queue, setQueue] = useState<TitleRequest[]>([]);
  const [stats, setStats] = useState<TitleStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [botAllianceTag, setBotAllianceTag] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [enableScientist, setEnableScientist] = useState(true);
  const [enableDuke, setEnableDuke] = useState(true);
  const [enableArchitect, setEnableArchitect] = useState(true);
  const [enableJustice, setEnableJustice] = useState(true);
  const [scientistHoldMinutes, setScientistHoldMinutes] = useState(DEFAULT_HOLD_MINUTES);
  const [dukeHoldMinutes, setDukeHoldMinutes] = useState(DEFAULT_HOLD_MINUTES);
  const [architectHoldMinutes, setArchitectHoldMinutes] = useState(DEFAULT_HOLD_MINUTES);
  const [justiceHoldMinutes, setJusticeHoldMinutes] = useState(DEFAULT_HOLD_MINUTES);
  const [reqName, setReqName] = useState("");
  const [reqTitle, setReqTitle] = useState<TitleType>("duke");
  const [reqTag, setReqTag] = useState("");
  const [reqGovId, setReqGovId] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [suggestions, setSuggestions] = useState<Array<{id: number; name: string; alliance: string}>>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [chatMessages, setChatMessages] = useState<LiveChatMessage[]>([]);
  const [chatFeedError, setChatFeedError] = useState(false);
  const [lastSeenChatId, setLastSeenChatId] = useState<number | null>(null);
  const [holdStatuses, setHoldStatuses] = useState<TitleHoldStatus[]>([]);

  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const applySettingsData = useCallback((data: Partial<TitleBotSettingsData>) => {
    if (data.bot_alliance_tag !== undefined) {
      setBotAllianceTag((data.bot_alliance_tag || "").toString());
    }
    if (data.enable_scientist !== undefined) setEnableScientist(Boolean(data.enable_scientist));
    if (data.enable_duke !== undefined) setEnableDuke(Boolean(data.enable_duke));
    if (data.enable_architect !== undefined) setEnableArchitect(Boolean(data.enable_architect));
    if (data.enable_justice !== undefined) setEnableJustice(Boolean(data.enable_justice));
    if (data.scientist_hold_minutes !== undefined) setScientistHoldMinutes(sanitizeHoldMinutes(Number(data.scientist_hold_minutes)));
    if (data.duke_hold_minutes !== undefined) setDukeHoldMinutes(sanitizeHoldMinutes(Number(data.duke_hold_minutes)));
    if (data.architect_hold_minutes !== undefined) setArchitectHoldMinutes(sanitizeHoldMinutes(Number(data.architect_hold_minutes)));
    if (data.justice_hold_minutes !== undefined) setJusticeHoldMinutes(sanitizeHoldMinutes(Number(data.justice_hold_minutes)));
    if (Array.isArray(data.hold_statuses)) setHoldStatuses(data.hold_statuses as TitleHoldStatus[]);
  }, []);

  const getConfiguredHoldMinutes = (titleType: TitleType) => {
    switch (titleType) {
      case "scientist":
        return scientistHoldMinutes;
      case "duke":
        return dukeHoldMinutes;
      case "architect":
        return architectHoldMinutes;
      case "justice":
        return justiceHoldMinutes;
      default:
        return DEFAULT_HOLD_MINUTES;
    }
  };

  const setConfiguredHoldMinutes = (titleType: TitleType, value: number) => {
    const nextValue = sanitizeHoldMinutes(value);
    switch (titleType) {
      case "scientist":
        setScientistHoldMinutes(nextValue);
        break;
      case "duke":
        setDukeHoldMinutes(nextValue);
        break;
      case "architect":
        setArchitectHoldMinutes(nextValue);
        break;
      case "justice":
        setJusticeHoldMinutes(nextValue);
        break;
    }
  };

  const getHoldStatus = (titleType: TitleType): TitleHoldStatus => {
    return holdStatuses.find((status) => status.title_type === titleType) || {
      title_type: titleType,
      hold_minutes: getConfiguredHoldMinutes(titleType),
      state: "available",
      available_at: null,
      current_holder_governor_id: null,
      current_holder_name: null,
    };
  };

  const fetchQueue = useCallback(async () => {
    try {
      const [queueRes, statsRes] = await Promise.all([
        fetch(`${apiUrl}/kingdoms/${kdNum}/titles/queue`),
        fetch(`${apiUrl}/kingdoms/${kdNum}/titles/stats`),
      ]);
      if (queueRes.ok) setQueue(await queueRes.json());
      if (statsRes.ok) setStats(await statsRes.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [apiUrl, kdNum]);

  const fetchSettings = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/kingdoms/${kdNum}/titles/settings`);
      if (!res.ok) return;
      const data = await res.json();
      applySettingsData(data);
    } catch { /* ignore */ }
  }, [apiUrl, applySettingsData, kdNum]);

  const fetchChatMessages = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/kingdoms/${kdNum}/game/chat-messages?limit=50`);
      if (!res.ok) {
        setChatFeedError(true);
        return;
      }

      const data = await res.json();
      const fetchedMessages: ChatMessage[] = Array.isArray(data?.messages) ? data.messages : [];
      const newestFetchedId = fetchedMessages.reduce((maxId, message) => {
        return typeof message?.id === "number" ? Math.max(maxId, message.id) : maxId;
      }, 0);

      if (lastSeenChatId === null) {
        setLastSeenChatId(newestFetchedId);
        setChatMessages([]);
        setChatFeedError(false);
        return;
      }

      const newLiveMessages: LiveChatMessage[] = fetchedMessages
        .filter((message) => typeof message?.id === "number" && message.id > lastSeenChatId)
        .map((message) => {
          const liveChannel = normalizeLiveChatChannel(message.channel);
          return liveChannel ? { ...message, liveChannel } : null;
        })
        .filter((message): message is LiveChatMessage => message !== null);

      if (newLiveMessages.length > 0) {
        setChatMessages((currentMessages) => {
          const seenIds = new Set(currentMessages.map((message) => message.id));
          const mergedMessages = [...currentMessages];

          for (const message of newLiveMessages) {
            if (!seenIds.has(message.id)) {
              mergedMessages.push(message);
              seenIds.add(message.id);
            }
          }

          return mergedMessages.slice(-60);
        });
      }

      if (newestFetchedId > lastSeenChatId) {
        setLastSeenChatId(newestFetchedId);
      }
      setChatFeedError(false);
    } catch {
      setChatFeedError(true);
    }
  }, [apiUrl, kdNum, lastSeenChatId]);

  useEffect(() => {
    setChatMessages([]);
    setChatFeedError(false);
    setLastSeenChatId(null);
  }, [kdNum, isTitleBotActive]);

  useEffect(() => {
    fetchQueue();
    fetchSettings();
    const interval = setInterval(() => {
      fetchQueue();
      fetchSettings();
    }, 10000);
    return () => clearInterval(interval);
  }, [fetchQueue, fetchSettings]);

  useEffect(() => {
    fetchChatMessages();
    const interval = setInterval(fetchChatMessages, 5000);
    return () => clearInterval(interval);
  }, [fetchChatMessages]);

  const handleSaveSettings = async () => {
    setSavingSettings(true);
    setMessage(null);
    try {
      const res = await fetch(`${apiUrl}/kingdoms/${kdNum}/titles/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          bot_alliance_tag: botAllianceTag.trim() ? botAllianceTag.trim().toUpperCase() : null,
          enable_scientist: enableScientist,
          enable_duke: enableDuke,
          enable_architect: enableArchitect,
          enable_justice: enableJustice,
          scientist_hold_minutes: scientistHoldMinutes,
          duke_hold_minutes: dukeHoldMinutes,
          architect_hold_minutes: architectHoldMinutes,
          justice_hold_minutes: justiceHoldMinutes,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setMessage({ type: "error", text: data.detail || "Failed to save settings" });
        return;
      }
      applySettingsData(data);
      setMessage({ type: "success", text: "Settings saved" });
    } catch {
      setMessage({ type: "error", text: "Failed to save settings" });
    } finally {
      setSavingSettings(false);
    }
  };

  const handleClearQueue = async () => {
    if (!confirm("Clear ALL pending title requests? This cannot be undone.")) return;
    try {
      const res = await fetch(`${apiUrl}/kingdoms/${kdNum}/titles/queue/clear?status=all`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const data = await res.json();
      if (res.ok) {
        setMessage({ type: "success", text: `Cleared ${data.cleared} requests` });
        fetchQueue();
      } else {
        setMessage({ type: "error", text: data.detail || "Failed to clear queue" });
      }
    } catch {
      setMessage({ type: "error", text: "Failed to clear queue" });
    }
  };

  const handleRequestTitle = async () => {
    const name = reqName.trim();
    if (!name || name.length < 2) {
      setMessage({ type: "error", text: "Enter a valid governor name" });
      return;
    }
    setSubmitting(true);
    setMessage(null);
    try {
      const res = await fetch(`${apiUrl}/kingdoms/${kdNum}/titles/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          governor_name: name,
          governor_id: reqGovId || 0,
          title_type: reqTitle,
          alliance_tag: reqTag.trim().toUpperCase() || botAllianceTag || null,
          duration_hours: 24,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setMessage({ type: "success", text: `Queued ${TITLE_INFO[reqTitle]?.name || reqTitle} for ${name}${reqGovId ? ` (ID: ${reqGovId})` : ""}` });
        setReqName("");
        setReqGovId(0);
        setShowSuggestions(false);
        fetchQueue();
      } else {
        setMessage({ type: "error", text: data.detail || "Failed to submit request" });
      }
    } catch {
      setMessage({ type: "error", text: "Failed to submit request" });
    } finally {
      setSubmitting(false);
    }
  };

  const searchGovernors = async (q: string) => {
    if (q.length < 2) { setSuggestions([]); return; }
    try {
      // Search scanned governors + snapshot data
      const [govRes, lookupRes] = await Promise.all([
        fetch(`${apiUrl}/kingdoms/${kdNum}/governors?search=${encodeURIComponent(q)}&limit=5`),
        fetch(`${apiUrl}/kingdoms/${kdNum}/game/player-lookup?query=${encodeURIComponent(q)}`),
      ]);
      const results: Array<{id: number; name: string; alliance: string}> = [];
      const seen = new Set<number>();
      if (govRes.ok) {
        const d = await govRes.json();
        for (const g of (d.items || [])) {
          if (g.governor_id && !seen.has(g.governor_id)) {
            seen.add(g.governor_id);
            results.push({ id: g.governor_id, name: g.name, alliance: g.alliance_tag || "" });
          }
        }
      }
      if (lookupRes.ok) {
        const d = await lookupRes.json();
        for (const r of (d.results || [])) {
          if (r.id && !seen.has(r.id)) {
            seen.add(r.id);
            results.push({ id: r.id, name: r.name, alliance: r.alliance || "" });
          }
        }
      }
      setSuggestions(results.slice(0, 8));
      setShowSuggestions(results.length > 0);
    } catch { /* ignore */ }
  };

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      pending: "bg-yellow-500/20 text-yellow-400",
      assigned: "bg-blue-500/20 text-blue-400",
      completed: "bg-green-500/20 text-green-400",
      failed: "bg-red-500/20 text-red-400",
      cancelled: "bg-gray-500/20 text-gray-400",
    };
    return (
      <span className={`px-2 py-1 rounded text-xs font-medium ${styles[status] || styles.pending}`}>
        {status.toUpperCase()}
      </span>
    );
  };

  const chatSections = LIVE_CHAT_SECTION_ORDER
    .map((channel) => ({
      channel,
      title: LIVE_CHAT_SECTION_TITLES[channel],
      messages: chatMessages.filter((message) => message.liveChannel === channel),
    }))
    .filter((section) => section.messages.length > 0);

  const selectedTitleHoldMinutes = getConfiguredHoldMinutes(reqTitle);

  return (
    <div className="space-y-6">
      {/* Title Bot Toggle */}
      <div className="bg-card border border-border rounded-xl p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-2xl ${
              isTitleBotActive ? "bg-purple-500/20" : "bg-zinc-700/30"
            }`}>
              👑
            </div>
            <div>
              <h3 className="text-lg font-semibold">Title Bot</h3>
              <p className="text-sm text-muted">
                {!isBotConnected
                  ? "Bot offline — start the bot first in the Control tab"
                  : isTitleBotActive
                    ? "Active — processing the title queue and running the live in-game title session"
                    : "Inactive — toggle to start giving titles automatically"}
              </p>
            </div>
          </div>
          <button
            onClick={onToggleTitleBot}
            disabled={togglingTitleBot || !isBotConnected}
            className={`relative inline-flex h-7 w-14 items-center rounded-full transition-colors duration-300 focus:outline-none disabled:opacity-40 ${
              isTitleBotActive ? "bg-purple-500" : "bg-zinc-600"
            }`}
          >
            <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-lg transition-transform duration-300 ${
              isTitleBotActive ? "translate-x-8" : "translate-x-1"
            }`} />
          </button>
        </div>
        {isTitleBotActive && (
          <div className="mt-4 p-3 bg-purple-500/10 border border-purple-500/30 rounded-lg">
            <div className="flex items-center gap-2 text-sm text-purple-300">
              <div className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
              <span>Live session active — queue requests are being executed in-game and chat capture stays attached when hooks are healthy.</span>
            </div>
          </div>
        )}
      </div>

      {/* Settings */}
      <div className="bg-card border border-border rounded-xl p-6">
        <h3 className="text-lg font-semibold mb-4">Title Settings</h3>
        <div className="grid md:grid-cols-3 gap-4 items-end">
          <div>
            <label className="block text-sm text-muted mb-1">Bot Alliance Tag</label>
            <input
              type="text"
              value={botAllianceTag}
              onChange={(e) => setBotAllianceTag(e.target.value.toUpperCase().slice(0, 10))}
              placeholder="e.g., TD65"
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            />
          </div>
          <button
            onClick={handleSaveSettings}
            disabled={savingSettings}
            className="py-2 px-4 bg-accent hover:bg-accent/80 text-bg font-medium rounded-lg transition-colors disabled:opacity-50"
          >
            {savingSettings ? "Saving..." : "Save Settings"}
          </button>
          <button
            onClick={handleClearQueue}
            className="py-2 px-4 bg-red-600 hover:bg-red-700 text-white font-medium rounded-lg transition-colors"
          >
            🗑️ Clear Queue
          </button>
        </div>

        {/* Title Type Toggles */}
        <div className="mt-6">
          <p className="text-sm text-muted mb-3">Enable/disable which titles the bot processes:</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {TITLE_SETTINGS_ORDER.map((titleType) => {
              const enabled =
                titleType === "scientist" ? enableScientist
                  : titleType === "duke" ? enableDuke
                  : titleType === "architect" ? enableArchitect
                  : enableJustice;
              const setEnabled =
                titleType === "scientist" ? setEnableScientist
                  : titleType === "duke" ? setEnableDuke
                  : titleType === "architect" ? setEnableArchitect
                  : setEnableJustice;

              return (
              <button
                key={titleType}
                type="button"
                onClick={() => setEnabled(!enabled)}
                className={`flex items-center gap-3 p-3 rounded-xl border transition-colors ${
                  enabled ? "border-accent/50 bg-accent/10" : "border-border bg-bg opacity-50"
                }`}
              >
                <div className={`w-10 h-5 rounded-full transition-colors relative ${enabled ? "bg-accent" : "bg-border"}`}>
                  <div className={`w-4 h-4 bg-white rounded-full absolute top-0.5 transition-transform ${enabled ? "translate-x-5" : "translate-x-0.5"}`} />
                </div>
                <span className="text-sm font-medium">{TITLE_INFO[titleType].icon} {TITLE_INFO[titleType].name}</span>
              </button>
              );
            })}
          </div>
          <p className="text-xs text-muted mt-2">Click &quot;Save Settings&quot; to persist changes.</p>
        </div>

        <div className="mt-6">
          <p className="text-sm text-muted mb-3">Minimum hold timer before the same title can be reassigned:</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {TITLE_SETTINGS_ORDER.map((titleType) => (
              <div key={`${titleType}-timer`} className="bg-bg border border-border rounded-xl p-3">
                <label className="block text-sm font-medium mb-2">{TITLE_INFO[titleType].icon} {TITLE_INFO[titleType].name}</label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={0}
                    max={1440}
                    value={getConfiguredHoldMinutes(titleType)}
                    onChange={(e) => setConfiguredHoldMinutes(titleType, Number(e.target.value))}
                    className="w-full bg-card border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
                  />
                  <span className="text-xs text-muted">min</span>
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted mt-2">Set to 0 to allow immediate reassignment after the current request completes.</p>
        </div>

        <div className="mt-6">
          <p className="text-sm text-muted mb-3">Current title availability:</p>
          <div className="grid md:grid-cols-2 gap-3">
            {TITLE_SETTINGS_ORDER.map((titleType) => {
              const holdStatus = getHoldStatus(titleType);
              const statusClass = HOLD_STATUS_STYLES[holdStatus.state] || "border-border bg-bg";

              return (
                <div key={`${titleType}-status`} className={`rounded-xl border p-4 ${statusClass}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-medium">{TITLE_INFO[titleType].icon} {TITLE_INFO[titleType].name}</p>
                      <p className="text-xs text-muted mt-1">Configured hold: {holdStatus.hold_minutes} min</p>
                    </div>
                    <span className="text-xs uppercase tracking-wide text-muted">{holdStatus.state.replace("_", " ")}</span>
                  </div>
                  <p className="text-sm mt-3">
                    {holdStatus.state === "in_progress"
                      ? `Being assigned${holdStatus.current_holder_name ? ` to ${holdStatus.current_holder_name}` : " right now"}`
                      : holdStatus.state === "cooldown"
                        ? `Held until ${formatAvailabilityTime(holdStatus.available_at)}`
                        : "Available now"}
                  </p>
                  {holdStatus.state === "cooldown" && holdStatus.current_holder_name && (
                    <p className="text-xs text-muted mt-1">Current holder: {holdStatus.current_holder_name}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Message */}
      {message && (
        <div className={`p-3 rounded-lg ${message.type === "success" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
          {message.text}
        </div>
      )}

      {/* Quick Title Request Form */}
      <div className="bg-card border border-border rounded-xl p-6">
        <h3 className="text-lg font-semibold mb-4">🎯 Request Title</h3>
        <div className="grid md:grid-cols-4 gap-3 items-end">
          <div className="relative">
            <label className="block text-sm text-muted mb-1">Governor {reqGovId ? <span className="text-green-400">(ID: {reqGovId})</span> : ""}</label>
            <input
              type="text"
              value={reqName}
              onChange={(e) => {
                setReqName(e.target.value);
                setReqGovId(0);
                searchGovernors(e.target.value);
              }}
              placeholder="Search governor..."
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
              onKeyDown={(e) => { if (e.key === "Enter") { setShowSuggestions(false); handleRequestTitle(); }}}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            />
            {showSuggestions && suggestions.length > 0 && (
              <div className="absolute z-10 top-full left-0 right-0 mt-1 bg-card border border-border rounded-lg shadow-lg max-h-48 overflow-y-auto">
                {suggestions.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className="w-full text-left px-3 py-2 hover:bg-zinc-700/30 text-sm"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      setReqName(s.name);
                      setReqGovId(s.id);
                      if (s.alliance) setReqTag(s.alliance);
                      setShowSuggestions(false);
                    }}
                  >
                    <span className="font-medium">{s.name}</span>
                    {s.alliance && <span className="text-muted ml-1">[{s.alliance}]</span>}
                    <span className="text-xs text-muted ml-2">ID: {s.id}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Title</label>
            <select
              value={reqTitle}
              onChange={(e) => setReqTitle(e.target.value as TitleType)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            >
              <option value="duke">⚒️ Duke</option>
              <option value="justice">⚔️ Justice</option>
              <option value="architect">🏗️ Architect</option>
              <option value="scientist">🔬 Scientist</option>
            </select>
            <p className="text-xs text-muted mt-1">
              {selectedTitleHoldMinutes > 0 ? `Hold after assignment: ${selectedTitleHoldMinutes} min` : "No hold after assignment"}
            </p>
          </div>
          <div>
            <label className="block text-sm text-muted mb-1">Alliance Tag</label>
            <input
              type="text"
              value={reqTag}
              onChange={(e) => setReqTag(e.target.value.toUpperCase().slice(0, 10))}
              placeholder={botAllianceTag || "optional"}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            />
          </div>
          <button
            onClick={handleRequestTitle}
            disabled={submitting || !reqName.trim()}
            className="py-2 px-4 bg-purple-600 hover:bg-purple-700 text-white font-medium rounded-lg transition-colors disabled:opacity-50"
          >
            {submitting ? "Sending..." : "➕ Add to Queue"}
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-card border border-yellow-500/30 rounded-xl p-4">
            <p className="text-xs text-yellow-300 uppercase tracking-wider mb-1">Queue</p>
            <p className="text-2xl font-bold">{stats.pending}</p>
          </div>
          <div className="bg-card border border-blue-500/30 rounded-xl p-4">
            <p className="text-xs text-blue-300 uppercase tracking-wider mb-1">In Progress</p>
            <p className="text-2xl font-bold">{stats.assigned}</p>
          </div>
          <div className="bg-card border border-green-500/30 rounded-xl p-4">
            <p className="text-xs text-green-300 uppercase tracking-wider mb-1">Done Today</p>
            <p className="text-2xl font-bold">{stats.completed_today}</p>
          </div>
          <div className="bg-card border border-purple-500/30 rounded-xl p-4">
            <p className="text-xs text-purple-300 uppercase tracking-wider mb-1">Wait Time</p>
            <p className="text-2xl font-bold">~{stats.queue_position_estimate_minutes}m</p>
          </div>
        </div>
      )}

      {/* Queue */}
      <div className="bg-card border border-border rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">📋 Title Queue</h3>
          <span className="text-xs text-muted">Auto-refreshes every 10s</span>
        </div>
        {loading ? (
          <div className="text-center py-8 text-muted">
            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2" />
            Loading...
          </div>
        ) : queue.length === 0 ? (
          <div className="text-center py-8 text-muted">
            <p className="mb-2">No pending or assigned requests</p>
            <p className="text-sm">Completed requests are hidden from this list. Open the Titles page to review recent completions.</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-[400px] overflow-y-auto">
            {queue.map((req, idx) => {
              const titleInfo = getTitleInfo(req.title_type);
              return (
                <div
                  key={req.id}
                  className={`flex items-center gap-3 p-3 rounded-lg ${
                    req.status === "assigned" ? "bg-blue-500/10 border border-blue-500/30" : "bg-bg"
                  }`}
                >
                  <div className="w-8 h-8 flex items-center justify-center rounded-full bg-border text-sm font-bold">
                    {idx + 1}
                  </div>
                  <span className="text-xl">{titleInfo?.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{req.governor_name}</p>
                    <div className="flex items-center gap-2 text-xs text-muted">
                      {req.alliance_tag && <span>[{req.alliance_tag}]</span>}
                      <span>{titleInfo?.name ?? req.title_type}</span>
                    </div>
                  </div>
                  {getStatusBadge(req.status)}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="bg-card border border-border rounded-xl p-6">
        <div className="flex items-center justify-between gap-3 mb-4">
          <div>
            <h3 className="text-lg font-semibold">💬 Live Chat</h3>
            <p className="text-xs text-muted mt-1">
              Only new live messages captured after this page was opened appear here automatically.
            </p>
          </div>
          <span className={`px-3 py-1 rounded-lg text-xs font-medium border ${
            chatFeedError
              ? "border-red-500/30 bg-red-500/10 text-red-300"
              : chatSections.length > 0
                ? "border-green-500/30 bg-green-500/10 text-green-300"
                : lastSeenChatId === null
                  ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                : isTitleBotActive
                  ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                  : "border-border bg-zinc-800 text-zinc-400"
          }`}>
            {chatFeedError
              ? "Feed unavailable"
              : chatSections.length > 0
                ? "Live feed active"
                : lastSeenChatId === null
                  ? "Syncing live feed"
                : isTitleBotActive
                  ? "Waiting for messages"
                  : "Bot inactive"}
          </span>
        </div>

        <div className="bg-bg border border-border rounded-xl overflow-hidden">
          {chatSections.length > 0 ? (
            <div className="max-h-[360px] overflow-y-auto space-y-4 p-4">
              {chatSections.map((section) => (
                <div key={section.channel} className="rounded-xl border border-border overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-2 bg-zinc-900/80 border-b border-border">
                    <span className="text-sm font-semibold text-foreground">{section.title}</span>
                    <span className="text-xs text-muted">{section.messages.length} live</span>
                  </div>
                  <div className="divide-y divide-border">
                    {section.messages.map((message) => {
                      const time = message.captured_at ? new Date(message.captured_at).toLocaleTimeString() : "";
                      const isTitleRequest = LIVE_CHAT_REQUEST_PATTERN.test(message.text || "");

                      return (
                        <div
                          key={message.id}
                          className={`px-4 py-3 ${isTitleRequest ? "bg-amber-500/5 border-l-2 border-l-amber-500" : ""}`}
                        >
                          <div className="flex items-center gap-2 text-xs text-muted">
                            {message.alliance_tag && <span className="text-blue-400">[{message.alliance_tag}]</span>}
                            <span className="font-medium text-foreground">{message.nickname || "Unknown"}</span>
                            <span className="ml-auto">{time}</span>
                          </div>
                          <p className="text-sm mt-1 text-foreground/90">
                            {message.text}
                            {isTitleRequest && (
                              <span className="ml-2 text-xs bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded">
                                Title Request
                              </span>
                            )}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-10 px-4 text-muted">
              <p className="text-3xl mb-2">💬</p>
              <p>{chatFeedError ? "The website could not read the live chat feed." : "No live DM, Kingdom, or Alliance chat captured yet"}</p>
              <p className="text-sm mt-1">
                {chatFeedError
                  ? "Check the backend API and the title bot session, then this box will start filling automatically."
                  : lastSeenChatId === null
                    ? "The panel is syncing to the current live session and ignoring older chat history."
                  : isTitleBotActive
                    ? "This panel stays empty until a new DM, Kingdom, or Alliance message arrives after the live feed sync."
                    : "Start the Title Bot to capture chat here and auto-detect title requests from chat."}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Info */}
      <div className="bg-card border border-blue-500/20 rounded-xl p-6 bg-gradient-to-r from-blue-900/20 to-purple-900/20">
        <h3 className="font-bold mb-2">ℹ️ How Titles Work</h3>
        <ul className="text-sm text-muted space-y-1">
          <li>• Activate the Title Bot here first — the queue stays authoritative, and the live Frida session executes requests in-game</li>
          <li>• Use this panel or the website to queue requests directly; chat capture can also feed the same queue when hooks are healthy</li>
          <li>• Bot gives titles via Frida/Lua handler — no UI navigation or OCR needed in the production path</li>
          <li>• PM can give: Justice, Duke, Architect, Scientist (titles 5-8)</li>
          <li>• Each positive title now respects its configured hold timer before the same slot is assigned to the next player</li>
        </ul>
      </div>
    </div>
  );
}
