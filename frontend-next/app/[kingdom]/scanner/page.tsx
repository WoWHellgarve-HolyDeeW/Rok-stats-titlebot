"use client";
import { useState, useEffect, useCallback } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import GameDataPanel from "@/components/GameDataPanel";
import TitleBotPanel from "@/components/TitleBotPanel";
import MapPanel from "@/components/MapPanel";

/* -- Types --------------------------------------------------------- */

interface BotStatus {
  status: "offline" | "idle" | "scanning" | "giving_titles" | "navigating" | "error" | "starting_game" | "reading_data" | "title_bot" | "map_scan" | "chat_monitor";
  message?: string;
  progress?: number;
  total?: number;
  updated_at?: string;
  scanner_available?: boolean;
  scanner_message?: string;
  scanner_checked_at?: string;
  profile_capture_available?: boolean;
  profile_capture_message?: string;
  profile_capture_checked_at?: string;
}

interface BotMode {
  mode: "idle" | "title_bot" | "scanning" | "profile_capture" | "paused" | "map_scan";
  scan_type?: string;
  scan_options?: Record<string, unknown>;
  updated_at?: string;
}

interface ScanStats {
  total_scans: number;
  total_governors: number;
  last_scan: string | null;
  alliances_count: number;
}

interface ImportResult {
  status: string;
  folder?: string;
  new_imports?: number;
  skipped?: number;
  errors?: number;
  results?: { status: string; file: string; imported?: number; kingdom?: number; message?: string }[];
}

interface LiveGovernor {
  rank: number;
  name: string;
  power: number;
  killpoints: number;
  t4_kills: number;
  t5_kills: number;
  deads: number;
  alliance: string;
}

/* -- Constants ----------------------------------------------------- */

const TABS = [
  { id: "control", label: "Control", icon: "\u26A1" },
  { id: "scanner", label: "Scanner", icon: "\uD83D\uDCCA" },
  { id: "titles", label: "Titles", icon: "\uD83D\uDC51" },
  { id: "game-data", label: "Game Data", icon: "\uD83C\uDFAE" },
  { id: "map", label: "Map", icon: "\uD83D\uDDFA\uFE0F" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const COUNT_PRESETS = [
  { label: "Free Run", value: 0 },
  { label: "Top 150", value: 150 },
  { label: "Top 300", value: 300 },
  { label: "Top 500", value: 500 },
  { label: "Top 1000", value: 1000 },
];

/* -- Page ---------------------------------------------------------- */

export default function BotControlPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const kingdom = params.kingdom as string;
  const { token, isAuthenticated, kingdom: authKingdom } = useAuth();
  const isAdmin = isAuthenticated && authKingdom === parseInt(kingdom);
  const requestedTab = searchParams.get("tab");

  const [activeTab, setActiveTab] = useState<TabId>("control");
  const [botStatus, setBotStatus] = useState<BotStatus>({ status: "offline" });
  const [botMode, setBotMode] = useState<BotMode>({ mode: "idle" });
  const [startingBot, setStartingBot] = useState(false);
  const [botError, setBotError] = useState<string | null>(null);
  const [stats, setStats] = useState<ScanStats | null>(null);
  const [scanCount, setScanCount] = useState(300);
  const [startingAction, setStartingAction] = useState<"scan" | "profile_capture" | null>(null);
  const [liveGovs, setLiveGovs] = useState<LiveGovernor[]>([]);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [togglingTitleBot, setTogglingTitleBot] = useState(false);

  const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  const isBotConnected = botStatus.status !== "offline";
  const isAutomatedScanMode = botMode.mode === "scanning";
  const isProfileCaptureMode = botMode.mode === "profile_capture";
  const isScanWorkflow = isAutomatedScanMode || isProfileCaptureMode;
  const isScanning = botStatus.status === "scanning" && !isProfileCaptureMode;
  const isProfileCaptureStarting = isProfileCaptureMode && botStatus.status === "starting_game";
  const isProfileCapturing = isProfileCaptureMode && botStatus.status === "scanning";
  const isTitleBotActive = botMode.mode === "title_bot" || botStatus.status === "giving_titles" || botStatus.status === "title_bot";
  const isStartingGame = botStatus.status === "starting_game" && !isProfileCaptureMode;
  const isReadingData = botStatus.status === "reading_data";
  const scannerAvailable = Boolean(botStatus.scanner_available);
  const scannerMessage = botStatus.scanner_message || "Automated scanner unavailable.";
  const profileCaptureAvailable = Boolean(botStatus.profile_capture_available);
  const profileCaptureMessage = botStatus.profile_capture_message || "Profile capture unavailable.";
  const activeWorkflowLabel = isProfileCaptureMode ? "Profile Capture" : "Automated Scanner";
  const progressLabel = isProfileCaptureMode ? "Capturing governor profiles..." : "Scanning governors...";
  const targetLabel = scanCount > 0 ? `Top ${scanCount}` : "Free Run";

  /* -- Fetchers ---------------------------------------------------- */

  const fetchBotStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/status`);
      if (res.ok) { const d = await res.json(); if (d.bot) setBotStatus(d.bot); }
    } catch { /* ignore */ }
  }, [API_URL, kingdom]);

  const fetchBotMode = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/mode`);
      if (res.ok) { const d = await res.json(); if (d.mode) setBotMode(d.mode); }
    } catch { /* ignore */ }
  }, [API_URL, kingdom]);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/summary`);
      if (res.ok) {
        const d = await res.json();
        setStats({
          total_scans: d.counts?.snapshots || 0,
          total_governors: d.counts?.governors || 0,
          alliances_count: d.counts?.alliances || 0,
          last_scan: d.last_scan,
        });
      }
    } catch { /* ignore */ }
  }, [API_URL, kingdom]);

  const fetchLiveGovs = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/live`);
      if (res.ok) { const d = await res.json(); if (d.governors) setLiveGovs(d.governors); }
    } catch { /* ignore */ }
  }, [API_URL, kingdom]);

  /* -- Effects ----------------------------------------------------- */

  useEffect(() => {
    fetchData(); fetchBotStatus(); fetchBotMode();
    const si = setInterval(() => { fetchBotStatus(); fetchBotMode(); }, 2000);
    const di = setInterval(fetchData, 15000);
    return () => { clearInterval(si); clearInterval(di); };
  }, [kingdom, fetchData, fetchBotStatus, fetchBotMode]);

  useEffect(() => {
    if (!isScanWorkflow) { setLiveGovs([]); return; }
    fetchLiveGovs();
    const li = setInterval(fetchLiveGovs, 3000);
    return () => clearInterval(li);
  }, [isScanWorkflow, fetchLiveGovs]);

  useEffect(() => {
    if (!requestedTab) return;
    if (TABS.some((tab) => tab.id === requestedTab)) {
      setActiveTab(requestedTab as TabId);
    }
  }, [requestedTab]);

  /* -- Actions ----------------------------------------------------- */

  const formatTimeAgo = (dateStr: string) => {
    const diff = Date.now() - new Date(dateStr).getTime();
    const m = Math.floor(diff / 60000);
    const h = Math.floor(m / 60);
    const d = Math.floor(h / 24);
    if (d > 0) return `${d}d ${h % 24}h ago`;
    if (h > 0) return `${h}h ${m % 60}m ago`;
    if (m > 0) return `${m}m ago`;
    return "Just now";
  };

  const startBot = async () => {
    if (!token) return;
    setStartingBot(true); setBotError(null);
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/start-daemon`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to start bot" }));
        setBotError(err.detail || "Failed to start bot");
      } else {
        await fetchBotStatus();
        await fetchBotMode();
      }
    } catch (e) { setBotError(String(e)); }
    finally { setStartingBot(false); }
  };

  const stopBot = async () => {
    if (!token) return;
    try { await fetch(`${API_URL}/kingdoms/${kingdom}/bot/stop-daemon`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    }); } catch { /* ignore */ }
  };

  const sendCommand = async (command: string, body?: Record<string, unknown>) => {
    if (!token) return;
    const p = new URLSearchParams({ command });
    const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/command?${p}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `Failed to send command '${command}'` }));
      throw new Error(err.detail || `Failed to send command '${command}'`);
    }
    return res.json().catch(() => null);
  };

  const startAutomatedScan = async () => {
    if (!token) return;
    if (!scannerAvailable) {
      setBotError(scannerMessage);
      return;
    }
    setStartingAction("scan");
    setBotError(null);
    try {
      const p = new URLSearchParams({ command: "start_scan", scan_type: "kingdom" });
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/command?${p}`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ count: scanCount }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to start scan" }));
        setBotError(err.detail || "Failed to start scan");
      } else {
        await fetchBotStatus();
        await fetchBotMode();
      }
    } catch (e) { setBotError(String(e)); }
    finally { setStartingAction(null); }
  };

  const startProfileCapture = async () => {
    if (!token) return;
    if (!profileCaptureAvailable) {
      setBotError(profileCaptureMessage);
      return;
    }
    setStartingAction("profile_capture");
    setBotError(null);
    try {
      const p = new URLSearchParams({ command: "start_profile_capture", scan_type: "kingdom" });
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/command?${p}`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ count: scanCount }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to start profile capture" }));
        setBotError(err.detail || "Failed to start profile capture");
      } else {
        await fetchBotStatus();
        await fetchBotMode();
      }
    } catch (e) { setBotError(String(e)); }
    finally { setStartingAction(null); }
  };

  const toggleTitleBot = async () => {
    if (!token) return;
    setTogglingTitleBot(true);
    setBotError(null);
    try {
      await sendCommand(isTitleBotActive ? "idle" : "start_title_bot");
      setBotMode(prev => ({ ...prev, mode: isTitleBotActive ? "idle" : "title_bot" }));
      await fetchBotStatus();
      await fetchBotMode();
    } catch (e) { setBotError(String(e)); }
    finally { setTogglingTitleBot(false); }
  };

  const importScansFromFolder = async () => {
    if (!token) return;
    setImporting(true); setImportResult(null);
    try {
      const res = await fetch(`${API_URL}/internal/import-scans`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      if (res.ok) { setImportResult(await res.json()); fetchData(); }
      else {
        const e = await res.json().catch(() => ({ detail: "Import failed" }));
        setImportResult({ status: "error", folder: e.detail || "Import failed" });
      }
    } catch (e) { setImportResult({ status: "error", folder: String(e) }); }
    finally { setImporting(false); }
  };

  /* -- Status helpers ---------------------------------------------- */

  const statusLabel = isProfileCaptureStarting ? "Starting Profile Capture..."
    : isProfileCapturing ? "Profile Capture..."
    : isStartingGame ? "Starting Game..."
    : isReadingData ? "Reading Game Data..."
    : isScanning ? "Scanning..."
    : botStatus.status === "giving_titles" ? "Giving Titles"
    : isTitleBotActive ? "Title Bot Active"
    : botStatus.status === "map_scan" ? "Map Scan..."
    : botStatus.status === "chat_monitor" ? "Chat Monitor"
    : botStatus.status === "idle" ? "Bot Idle"
    : botStatus.status === "navigating" ? "Navigating"
    : botStatus.status === "error" ? "Error"
    : "Bot Offline";

  /* -- Render ------------------------------------------------------ */

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Bot Control</h1>
        <p className="text-muted text-sm">Manage the Frida daemon &mdash; titles, scans, and game data</p>
      </div>

      {/* Global Status Bar */}
      <div className="bg-card border border-border rounded-xl p-4 flex items-center gap-4">
        <div className={`w-3 h-3 rounded-full ${
          isBotConnected ? (isProfileCaptureStarting || isProfileCapturing ? "bg-cyan-400 animate-pulse" : isStartingGame || isReadingData ? "bg-yellow-400 animate-pulse" : isScanning ? "bg-blue-400 animate-pulse" : isTitleBotActive ? "bg-purple-400 animate-pulse" : "bg-green-400") : "bg-zinc-500"
        }`} />
        <div className="flex-1">
          <span className="font-semibold">{statusLabel}</span>
          {botStatus.message && <span className="text-sm text-muted ml-2">&mdash; {botStatus.message}</span>}
        </div>
        {botStatus.updated_at && <span className="text-xs text-muted">{formatTimeAgo(botStatus.updated_at)}</span>}
        {isScanWorkflow && botStatus.progress !== undefined && botStatus.total !== undefined && botStatus.total > 0 && (
          <span className="text-sm font-mono text-blue-400">
            {botStatus.progress}/{botStatus.total} ({Math.round((botStatus.progress / botStatus.total) * 100)}%)
          </span>
        )}
      </div>

      {/* Tab Bar */}
      <div className="flex gap-1 bg-card border border-border rounded-xl p-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.id
                ? "bg-accent/15 text-accent border border-accent/30"
                : "text-muted hover:text-text hover:bg-card-hover border border-transparent"
            }`}
          >
            <span>{tab.icon}</span>
            <span className="hidden sm:inline">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* ============ CONTROL TAB ============ */}
      {activeTab === "control" && (
        <div className="space-y-6">
          <div className="bg-card border border-border rounded-xl p-6">
            <div className="flex items-center gap-4 mb-6">
              <div className={`w-14 h-14 rounded-xl flex items-center justify-center text-3xl ${
                isProfileCaptureStarting || isProfileCapturing ? "bg-cyan-500/20" : isStartingGame || isReadingData ? "bg-yellow-500/20" : isScanning ? "bg-blue-500/20" : isTitleBotActive ? "bg-purple-500/20" : isBotConnected ? "bg-green-500/20" : "bg-zinc-700/30"
              }`}>
                {isProfileCaptureStarting || isProfileCapturing ? "\uD83D\uDD0E" : isStartingGame ? "\u23F3" : isReadingData ? "\uD83D\uDCE1" : isScanning ? "\uD83D\uDCCA" : isTitleBotActive ? "\uD83D\uDC51" : isBotConnected ? "\u2705" : "\u2B55"}
              </div>
              <div>
                <h2 className="text-xl font-bold">{statusLabel}</h2>
                <p className="text-sm text-muted">
                  {isProfileCaptureStarting || isProfileCapturing ? "Temporary profile capture is active while the automated scanner is being rebuilt."
                    : isStartingGame ? "Launching Rise of Kingdoms in emulator..."
                    : isReadingData ? "Reading Lua game state via Frida..."
                    : isBotConnected ? "Frida daemon connected to Rise of Kingdoms"
                    : "Bot is not running \u2014 start it to enable scanning and titles"}
                </p>
              </div>
            </div>

            {isScanWorkflow && botStatus.progress !== undefined && botStatus.total !== undefined && botStatus.total > 0 && (() => {
              const pct = Math.min(100, Math.round((botStatus.progress! / botStatus.total!) * 100));
              return (
                <div className="mb-6 p-4 bg-blue-500/10 border border-blue-500/30 rounded-xl">
                  <div className="flex justify-between items-center text-sm mb-3">
                    <span className="text-blue-400 font-medium">{progressLabel}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-blue-400 font-mono text-xs">{botStatus.progress} / {botStatus.total}</span>
                      <span className="text-blue-300 font-bold tabular-nums">{pct}%</span>
                    </div>
                  </div>
                  <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-700 ease-out shadow-[0_0_8px_rgba(59,130,246,0.5)]"
                      style={{ width: `${Math.max(pct > 0 ? 2 : 0, pct)}%` }}
                    />
                  </div>
                </div>
              );
            })()}

            {!isBotConnected && isAdmin && (
              <div className="space-y-3">
                <button onClick={startBot} disabled={startingBot}
                  className="w-full py-3.5 px-4 bg-green-500 hover:bg-green-600 disabled:bg-green-500/50 text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2 text-base">
                  {startingBot ? (<><svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg> Starting bot...</>)
                  : (<><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg> Start Bot</>)}
                </button>
                {botError && <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">{botError}</div>}
                <p className="text-xs text-muted text-center">Requires LDPlayer emulator running (1600x900). Game will start automatically.</p>
              </div>
            )}

            {!isBotConnected && !isAdmin && (
              <div className="p-4 bg-zinc-800/50 border border-border rounded-lg">
                <p className="text-sm text-muted">Bot is offline. Contact an administrator to start it.</p>
              </div>
            )}

            {isScanWorkflow && (
              <button onClick={() => sendCommand("stop")}
                className="w-full py-3 px-4 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1" /></svg> {isProfileCaptureMode ? "Stop Profile Capture" : "Stop Scan"}
              </button>
            )}

            {isBotConnected && !isScanWorkflow && isAdmin && (
              <div className="flex items-center justify-between pt-2 border-t border-border/30 mt-4">
                <span className="text-sm text-muted">Bot daemon is running</span>
                <button onClick={stopBot} className="text-xs text-muted hover:text-red-400 transition-colors py-1 px-3 rounded border border-border hover:border-red-500/30">
                  Disconnect Bot
                </button>
              </div>
            )}
          </div>

          {isBotConnected && isAdmin && !isScanWorkflow && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <button onClick={() => setActiveTab("scanner")}
                className="bg-card border border-border rounded-xl p-5 text-left hover:border-blue-500/30 transition-colors group">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-2xl">{"\uD83D\uDCCA"}</span>
                  <span className="font-semibold group-hover:text-blue-400 transition-colors">Scanner Workbench</span>
                </div>
                <p className="text-sm text-muted">Check automated scanner readiness and use temporary profile capture if needed</p>
              </button>
              <button onClick={() => setActiveTab("titles")}
                className="bg-card border border-border rounded-xl p-5 text-left hover:border-purple-500/30 transition-colors group">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-2xl">{"\uD83D\uDC51"}</span>
                  <span className="font-semibold group-hover:text-purple-400 transition-colors">
                    Title Bot {isTitleBotActive ? "(Active)" : "(Inactive)"}
                  </span>
                </div>
                <p className="text-sm text-muted">Manage the title queue and in-game title automation</p>
              </button>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-card border border-border rounded-xl p-4">
              <p className="text-sm text-muted">Snapshots</p>
              <p className="text-2xl font-bold">{stats?.total_scans?.toLocaleString() || 0}</p>
            </div>
            <div className="bg-card border border-border rounded-xl p-4">
              <p className="text-sm text-muted">Governors</p>
              <p className="text-2xl font-bold">{stats?.total_governors?.toLocaleString() || 0}</p>
            </div>
            <div className="bg-card border border-border rounded-xl p-4">
              <p className="text-sm text-muted">Alliances</p>
              <p className="text-2xl font-bold">{stats?.alliances_count?.toLocaleString() || 0}</p>
            </div>
            <div className="bg-card border border-border rounded-xl p-4">
              <p className="text-sm text-muted">Last Scan</p>
              <p className="text-lg font-bold">{stats?.last_scan ? formatTimeAgo(stats.last_scan) : "Never"}</p>
            </div>
          </div>
        </div>
      )}

      {/* ============ SCANNER TAB ============ */}
      {activeTab === "scanner" && (
        <div className="space-y-6">
          {isAdmin && isBotConnected && !isScanWorkflow && (
            <>
              <div className="bg-card border border-border rounded-xl p-6">
                <h3 className="text-lg font-semibold mb-2">Target Profiles</h3>
                <p className="text-sm text-muted mb-4">Choose an optional target size once. For discovery runs, use Free Run and stop manually when you have enough signal.</p>
                <div className="flex gap-2 flex-wrap">
                  {COUNT_PRESETS.map((p) => (
                    <button key={p.value} onClick={() => setScanCount(p.value)}
                      className={`py-2 px-4 rounded-lg border text-sm font-medium transition-all ${
                        scanCount === p.value ? "border-blue-500 bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/40" : "border-border hover:border-blue-500/40"
                      }`}>{p.label}</button>
                  ))}
                  <div className="flex items-center gap-2">
                    <input type="number" value={scanCount}
                      onChange={(e) => setScanCount(Math.max(0, Math.min(5000, parseInt(e.target.value) || 0)))}
                      className="w-20 py-2 px-3 bg-bg border border-border rounded-lg text-sm text-center focus:border-blue-500 focus:outline-none" min={0} max={5000} />
                    <span className="text-xs text-muted">custom</span>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <div className="bg-card border border-border rounded-xl p-6">
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div>
                      <h3 className="text-lg font-semibold mb-1">Automated Scanner</h3>
                      <p className="text-sm text-muted">Reserved for the rebuilt orchestrated scan flow. This is the non-manual path we want to restore.</p>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${scannerAvailable ? "bg-green-500/15 text-green-300 border border-green-500/30" : "bg-amber-500/15 text-amber-300 border border-amber-500/30"}`}>
                      {scannerAvailable ? "Available" : "Rebuilding"}
                    </span>
                  </div>
                  <button onClick={startAutomatedScan} disabled={startingAction !== null || !scannerAvailable}
                    className="w-full py-3.5 px-4 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2 text-base disabled:cursor-not-allowed">
                    {startingAction === "scan" ? (<><svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg> Sending...</>)
                    : (<><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg> Start Automated Scan &mdash; {targetLabel}</>)}
                  </button>
                  <div className={`mt-3 rounded-lg border px-3 py-2 text-sm ${scannerAvailable ? "border-green-500/30 bg-green-500/10 text-green-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300"}`}>
                    {scannerMessage}
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-6">
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div>
                      <h3 className="text-lg font-semibold mb-1">Temporary Profile Capture</h3>
                      <p className="text-sm text-muted">Diagnostic bridge while the automated scanner is unavailable. Runs passive Frida capture and depends on manual profile clicks.</p>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${profileCaptureAvailable ? "bg-cyan-500/15 text-cyan-300 border border-cyan-500/30" : "bg-amber-500/15 text-amber-300 border border-amber-500/30"}`}>
                      {profileCaptureAvailable ? "Available" : "Unavailable"}
                    </span>
                  </div>
                  <button onClick={startProfileCapture} disabled={startingAction !== null || !profileCaptureAvailable}
                    className="w-full py-3.5 px-4 bg-cyan-500 hover:bg-cyan-600 disabled:bg-cyan-500/50 text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2 text-base disabled:cursor-not-allowed">
                    {startingAction === "profile_capture" ? (<><svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg> Sending...</>)
                    : (<><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7m-7 0a18.023 18.023 0 003.588-5.5m-3.588 5.5l-3.588-5.5m3.588 5.5V9" /></svg> Start Profile Capture &mdash; {targetLabel}</>)}
                  </button>
                  {!profileCaptureAvailable && (
                    <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
                      {profileCaptureMessage}
                    </div>
                  )}
                  <p className="text-xs text-muted mt-3">Use Rankings &gt; Power or another governor list, keep the sniffer running, and open profiles manually. In Free Run the capture stays open until you stop it yourself.</p>
                </div>
              </div>
            </>
          )}

          {botError && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {botError}
            </div>
          )}

          {isScanWorkflow && (
            <div className="bg-card border border-blue-500/30 rounded-xl p-6">
              <div className="mb-4">
                <h3 className="text-lg font-semibold">{activeWorkflowLabel} Running</h3>
                <p className="text-sm text-muted">{isProfileCaptureMode ? "Temporary manual capture is collecting live profile data while you click through governors." : "Automated scanner is driving the scan flow."}</p>
              </div>
              {botStatus.progress !== undefined && botStatus.total !== undefined && botStatus.total > 0 && (() => {
                const pct = Math.min(100, Math.round((botStatus.progress! / botStatus.total!) * 100));
                return (
                  <div className="mb-4">
                    <div className="flex justify-between items-center text-sm mb-3">
                      <span className="text-blue-400 font-medium">{progressLabel}</span>
                      <div className="flex items-center gap-3">
                        <span className="text-blue-400 font-mono text-xs">{botStatus.progress} / {botStatus.total}</span>
                        <span className="text-blue-300 font-bold tabular-nums">{pct}%</span>
                      </div>
                    </div>
                    <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-700 ease-out shadow-[0_0_8px_rgba(59,130,246,0.5)]"
                        style={{ width: `${Math.max(pct > 0 ? 2 : 0, pct)}%` }}
                      />
                    </div>
                  </div>
                );
              })()}
              <button onClick={() => sendCommand("stop")}
                className="w-full py-3 px-4 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2">
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1" /></svg> {isProfileCaptureMode ? "Stop Profile Capture" : "Stop Automated Scan"}
              </button>
            </div>
          )}

          {!isBotConnected && (
            <div className="bg-card border border-border rounded-xl p-8 text-center">
              <p className="text-lg text-muted mb-2">Bot is offline</p>
              <p className="text-sm text-muted">Go to the <button onClick={() => setActiveTab("control")} className="text-accent hover:underline">Control</button> tab to start the bot first.</p>
            </div>
          )}

          {liveGovs.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">Live Governor Profiles</h3>
                <span className="text-sm text-muted font-mono">{liveGovs.length} governors</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-muted">
                      <th className="pb-2 pr-3 font-medium">#</th>
                      <th className="pb-2 pr-3 font-medium">Name</th>
                      <th className="pb-2 pr-3 font-medium text-right">Power</th>
                      <th className="pb-2 pr-3 font-medium text-right">Kill Points</th>
                      <th className="pb-2 pr-3 font-medium text-right">T4 Kills</th>
                      <th className="pb-2 pr-3 font-medium text-right">T5 Kills</th>
                      <th className="pb-2 font-medium text-right">Dead</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liveGovs.map((g, i) => (
                      <tr key={i} className={`border-b border-border/50 ${i === liveGovs.length - 1 ? "bg-blue-500/5" : ""}`}>
                        <td className="py-1.5 pr-3 text-muted font-mono">{g.rank}</td>
                        <td className="py-1.5 pr-3 font-medium truncate max-w-[160px]">
                          {g.alliance && <span className="text-muted text-xs mr-1">[{g.alliance.replace(/^\[|\]$/g, "").slice(0, 6)}]</span>}
                          {g.name || "?"}
                        </td>
                        <td className="py-1.5 pr-3 text-right font-mono">{(g.power || 0).toLocaleString()}</td>
                        <td className="py-1.5 pr-3 text-right font-mono">{(g.killpoints || 0).toLocaleString()}</td>
                        <td className="py-1.5 pr-3 text-right font-mono">{(g.t4_kills || 0).toLocaleString()}</td>
                        <td className="py-1.5 pr-3 text-right font-mono">{(g.t5_kills || 0).toLocaleString()}</td>
                        <td className="py-1.5 text-right font-mono">{(g.deads || 0).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {isAdmin && (
            <div className="bg-card border border-border rounded-xl p-6">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-green-500 to-emerald-500 flex items-center justify-center flex-shrink-0">
                  <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold mb-1">Import Scans</h3>
                  <p className="text-sm text-muted mb-3">Import CSV scan files into the database.</p>
                  <button onClick={importScansFromFolder} disabled={importing}
                    className="py-2.5 px-5 bg-green-500 hover:bg-green-600 disabled:bg-green-500/50 text-white font-semibold rounded-lg transition-colors flex items-center gap-2 text-sm">
                    {importing ? (<><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg> Importing...</>) : "Import from Server"}
                  </button>
                  {importResult && (
                    <div className={`mt-3 p-3 rounded-lg border text-sm ${importResult.status === "error" ? "bg-red-500/10 border-red-500/30 text-red-400" : "bg-green-500/10 border-green-500/30"}`}>
                      {importResult.status === "error" ? <p>{importResult.folder}</p> : (
                        <div className="flex items-center gap-4">
                          <span className="text-green-400"><strong>{importResult.new_imports}</strong> new</span>
                          <span className="text-muted"><strong>{importResult.skipped}</strong> skipped</span>
                          {importResult.errors ? <span className="text-red-400"><strong>{importResult.errors}</strong> errors</span> : null}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ============ TITLES TAB ============ */}
      {activeTab === "titles" && (
        <TitleBotPanel
          kingdom={kingdom} token={token} apiUrl={API_URL}
          isBotConnected={isBotConnected} isTitleBotActive={isTitleBotActive}
          onToggleTitleBot={toggleTitleBot} togglingTitleBot={togglingTitleBot}
        />
      )}

      {/* ============ GAME DATA TAB ============ */}
      {activeTab === "game-data" && (
        <GameDataPanel
          kingdom={kingdom}
          token={token}
          apiUrl={API_URL}
          isBotConnected={isBotConnected}
          isTitleBotActive={isTitleBotActive}
        />
      )}

      {/* ============ MAP TAB ============ */}
      {activeTab === "map" && (
        <MapPanel kingdom={kingdom} token={token} isBotConnected={isBotConnected} />
      )}
    </div>
  );
}