"use client";
import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@/lib/auth";

interface ScanStats {
  total_scans: number;
  total_governors: number;
  last_scan: string | null;
  alliances_count: number;
}

interface BotStatus {
  status: "offline" | "idle" | "navigating" | "scanning" | "giving_titles" | "error";
  message?: string;
  progress?: number;
  total?: number;
  updated_at?: string;
}

interface BotMode {
  mode: "idle" | "title_bot" | "scanning" | "paused";
  scan_type?: string;
  scan_options?: Record<string, unknown>;
  updated_at?: string;
  requested_by?: string;
}

interface ImportResult {
  status: string;
  folder?: string;
  total_files?: number;
  new_imports?: number;
  skipped?: number;
  errors?: number;
  results?: { status: string; file: string; imported?: number; kingdom?: number; message?: string }[];
}

type ScanType = "kingdom" | "alliance" | "honor" | "seed";

export default function ScannerPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const { token, isAuthenticated, kingdom: authKingdom } = useAuth();
  const isAdmin = isAuthenticated && authKingdom === parseInt(kingdom);
  const [stats, setStats] = useState<ScanStats | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatus>({ status: "offline" });
  const [botMode, setBotMode] = useState<BotMode>({ mode: "idle" });
  const [, setLoading] = useState(true);
  const [showScanModal, setShowScanModal] = useState(false);
  const [selectedScanType, setSelectedScanType] = useState<ScanType>("kingdom");
  const [scanAmount, setScanAmount] = useState(1000);
  const [sending, setSending] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  const fetchBotStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/status`);
      if (res.ok) {
        const data = await res.json();
        if (data.bot) {
          setBotStatus(data.bot);
        }
      }
    } catch (error) {
      console.error("Error fetching bot status:", error);
    }
  }, [API_URL, kingdom]);

  const fetchBotMode = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/mode`);
      if (res.ok) {
        const data = await res.json();
        if (data.mode) {
          setBotMode(data.mode);
        }
      }
    } catch (error) {
      console.error("Error fetching bot mode:", error);
    }
  }, [API_URL, kingdom]);

  const fetchData = useCallback(async () => {
    try {
      const summaryRes = await fetch(`${API_URL}/kingdoms/${kingdom}/summary`);
      if (summaryRes.ok) {
        const data = await summaryRes.json();
        setStats({
          total_scans: data.counts?.snapshots || 0,
          total_governors: data.counts?.governors || 0,
          alliances_count: data.counts?.alliances || 0,
          last_scan: data.last_scan,
        });
      }
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  }, [API_URL, kingdom]);

  useEffect(() => {
    fetchData();
    fetchBotStatus();
    fetchBotMode();
    // Poll bot status every 3 seconds
    const statusInterval = setInterval(() => {
      fetchBotStatus();
      fetchBotMode();
    }, 3000);
    // Refresh stats less frequently
    const dataInterval = setInterval(fetchData, 30000);
    return () => {
      clearInterval(statusInterval);
      clearInterval(dataInterval);
    };
  }, [kingdom, fetchData, fetchBotStatus, fetchBotMode]);

  const setBotModeAPI = async (mode: BotMode["mode"], scanType?: string) => {
    setSending(true);
    try {
      const params = new URLSearchParams({ mode });
      if (scanType) params.append("scan_type", scanType);
      
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/mode?${params}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      
      if (res.ok) {
        fetchBotMode();
        fetchBotStatus();
      }
    } catch (error) {
      console.error("Error setting bot mode:", error);
    } finally {
      setSending(false);
    }
  };

  const sendBotCommand = async (command: string, scanType?: ScanType, options?: Record<string, unknown>) => {
    setSending(true);
    try {
      const params = new URLSearchParams({ command });
      if (scanType) params.append("scan_type", scanType);
      
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/command?${params}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: options ? JSON.stringify(options) : undefined,
      });
      
      if (res.ok) {
        setShowScanModal(false);
        fetchBotStatus();
        fetchBotMode();
      }
    } catch (error) {
      console.error("Error sending command:", error);
    } finally {
      setSending(false);
    }
  };

  const formatTimeAgo = (dateStr: string) => {
    const now = new Date();
    const date = new Date(dateStr);
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / (1000 * 60));
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ${hours % 24}h ago`;
    if (hours > 0) return `${hours}h ${minutes % 60}m ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return "Just now";
  };

  const getStatusColor = (status: BotStatus["status"]) => {
    switch (status) {
      case "idle": return "text-green-500";
      case "scanning": return "text-blue-500";
      case "giving_titles": return "text-yellow-500";
      case "navigating": return "text-purple-500";
      case "error": return "text-red-500";
      default: return "text-muted";
    }
  };

  const getModeLabel = (mode: BotMode["mode"]) => {
    switch (mode) {
      case "title_bot": return "Title Bot";
      case "scanning": return "Ready to Scan";
      case "paused": return "Paused";
      default: return "Idle";
    }
  };

  const getModeDescription = (mode: BotMode["mode"]) => {
    switch (mode) {
      case "title_bot": return "Bot is monitoring chat for title requests";
      case "scanning": return "Title bot paused. Navigate to Rankings in game, then click 'Start Scan'";
      case "paused": return "Bot is completely paused";
      default: return "Bot is waiting for commands";
    }
  };

  const isBotBusy = botStatus.status === "scanning" || botStatus.status === "giving_titles" || botStatus.status === "navigating";
  const isBotConnected = botStatus.status !== "offline";

  const importScansFromFolder = async () => {
    if (!token) return;
    setImporting(true);
    setImportResult(null);
    try {
      // Usa o endpoint interno que aceita token de kingdom
      // ou o endpoint admin com token admin
      const res = await fetch(`${API_URL}/internal/import-scans`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      if (res.ok) {
        const data = await res.json();
        setImportResult(data);
        // Refresh stats after import
        fetchData();
      } else {
        const error = await res.json().catch(() => ({ detail: "Import failed" }));
        setImportResult({ status: "error", folder: error.detail || "Import failed" });
      }
    } catch (error) {
      setImportResult({ status: "error", folder: String(error) });
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Bot Control</h1>
          <p className="text-muted">Control the bot and run scans</p>
        </div>
      </div>

      {/* Unified Bot Control Card */}
      <div className="bg-card border border-border rounded-xl p-6">
        {/* Header with connection status */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-2xl ${
              !isBotConnected ? "bg-gray-500/20" : 
              botMode.mode === "title_bot" ? "bg-yellow-500/20" :
              botMode.mode === "scanning" ? "bg-blue-500/20" :
              botMode.mode === "paused" ? "bg-orange-500/20" : "bg-green-500/20"
            }`}>
              <span className={getStatusColor(isBotConnected ? (
                botMode.mode === "title_bot" ? "giving_titles" :
                botMode.mode === "scanning" ? "scanning" : "idle"
              ) : "offline")}>
                {!isBotConnected ? "○" : 
                 botMode.mode === "title_bot" ? "★" :
                 botMode.mode === "scanning" ? "📊" :
                 botMode.mode === "paused" ? "⛔" : "●"}
              </span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold">{getModeLabel(botMode.mode)}</h2>
                {isBotConnected && (
                  <span className="px-2 py-0.5 rounded-full text-xs bg-green-500/20 text-green-400">
                    Connected
                  </span>
                )}
              </div>
              <p className="text-sm text-muted">{getModeDescription(botMode.mode)}</p>
            </div>
          </div>
          {botStatus.updated_at && (
            <span className="text-xs text-muted">
              {formatTimeAgo(botStatus.updated_at)}
            </span>
          )}
        </div>

        {/* Progress bar - only show when actually scanning with real progress */}
        {botStatus.status === "scanning" && botStatus.progress !== undefined && botStatus.total !== undefined && botStatus.total > 0 && (
          <div className="mb-6 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg">
            <div className="flex justify-between text-sm mb-2">
              <span className="text-blue-400">Scanning in progress...</span>
              <span className="text-blue-400">{botStatus.progress} / {botStatus.total}</span>
            </div>
            <div className="h-2 bg-border rounded-full overflow-hidden">
              <div 
                className="h-full bg-blue-500 transition-all duration-300"
                style={{ width: `${(botStatus.progress / botStatus.total) * 100}%` }}
              />
            </div>
            {botStatus.message && (
              <p className="text-xs text-muted mt-2">{botStatus.message}</p>
            )}
          </div>
        )}

        {/* Mode Selection Buttons */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <button
            onClick={() => setBotModeAPI("idle")}
            disabled={sending || !isBotConnected}
            className={`py-4 px-4 rounded-lg border font-medium transition-all ${
              botMode.mode === "idle" 
                ? "border-green-500 bg-green-500/20 text-green-400 ring-2 ring-green-500/30" 
                : "border-border hover:border-green-500/50 hover:bg-green-500/5"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <div className="text-2xl mb-2">⏸</div>
            <div className="text-sm font-semibold">Idle</div>
            <div className="text-xs text-muted mt-1">Wait for commands</div>
          </button>

          <button
            onClick={() => setBotModeAPI("title_bot")}
            disabled={sending || !isBotConnected}
            className={`py-4 px-4 rounded-lg border font-medium transition-all ${
              botMode.mode === "title_bot" 
                ? "border-yellow-500 bg-yellow-500/20 text-yellow-400 ring-2 ring-yellow-500/30" 
                : "border-border hover:border-yellow-500/50 hover:bg-yellow-500/5"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <div className="text-2xl mb-2">★</div>
            <div className="text-sm font-semibold">Title Bot</div>
            <div className="text-xs text-muted mt-1">Auto-give titles</div>
          </button>

          <button
            onClick={() => setBotModeAPI("scanning")}
            disabled={sending || !isBotConnected}
            className={`py-4 px-4 rounded-lg border font-medium transition-all ${
              botMode.mode === "scanning" 
                ? "border-blue-500 bg-blue-500/20 text-blue-400 ring-2 ring-blue-500/30" 
                : "border-border hover:border-blue-500/50 hover:bg-blue-500/5"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <div className="text-2xl mb-2">📊</div>
            <div className="text-sm font-semibold">Prepare Scan</div>
            <div className="text-xs text-muted mt-1">Pause for scanning</div>
          </button>

          <button
            onClick={() => setBotModeAPI("paused")}
            disabled={sending || !isBotConnected}
            className={`py-4 px-4 rounded-lg border font-medium transition-all ${
              botMode.mode === "paused" 
                ? "border-orange-500 bg-orange-500/20 text-orange-400 ring-2 ring-orange-500/30" 
                : "border-border hover:border-orange-500/50 hover:bg-orange-500/5"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            <div className="text-2xl mb-2">⛔</div>
            <div className="text-sm font-semibold">Pause</div>
            <div className="text-xs text-muted mt-1">Stop everything</div>
          </button>
        </div>

        {/* Stop button when busy */}
        {isBotBusy && (
          <button
            onClick={() => sendBotCommand("stop")}
            className="w-full py-3 px-4 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
            </svg>
            Stop Current Operation
          </button>
        )}

        {/* Bot offline warning */}
        {!isBotConnected && (
          <div className="mt-4 p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-3">
            <svg className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <p className="font-semibold text-red-400">Bot Not Connected</p>
              <p className="text-sm text-muted">The scanner bot is currently offline.</p>
            </div>
          </div>
        )}
      </div>

      {/* Stats Grid */}
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

      {/* Scanner Card - Only shown when in scanning mode */}
      <div className={`bg-card border rounded-xl p-6 transition-all ${
        botMode.mode === "scanning" 
          ? "border-blue-500 ring-2 ring-blue-500/20" 
          : "border-border"
      }`}>
        <div className="flex items-start gap-4">
          <div className={`w-14 h-14 rounded-xl flex items-center justify-center flex-shrink-0 ${
            botMode.mode === "scanning" 
              ? "bg-gradient-to-br from-blue-500 to-cyan-500" 
              : "bg-gradient-to-br from-accent to-accent2"
          }`}>
            <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold mb-1">Kingdom Scanner</h3>
            {botMode.mode === "scanning" ? (
              <div className="space-y-3">
                <div className="p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                  <p className="text-sm text-blue-400 font-medium">Ready to scan!</p>
                  <ol className="text-sm text-muted mt-2 space-y-1 list-decimal list-inside">
                    <li>Open RoK and go to <strong>Rankings → Individual Power</strong></li>
                    <li>Make sure the list is visible on screen</li>
                    <li>Click &quot;Start Scan&quot; below</li>
                  </ol>
                </div>
                <button
                  onClick={() => setShowScanModal(true)}
                  disabled={isBotBusy || !isBotConnected}
                  className="w-full py-3 px-4 bg-blue-500 hover:bg-blue-600 disabled:bg-border disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Start Scan
                </button>
              </div>
            ) : (
              <>
                <p className="text-sm text-muted mb-4">
                  To run a scan, first click &quot;Prepare Scan&quot; above to pause the title bot, then open Rankings in game.
                </p>
                <button
                  onClick={() => setBotModeAPI("scanning")}
                  disabled={sending || !isBotConnected || isBotBusy}
                  className="w-full py-3 px-4 bg-border hover:bg-border/80 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors flex items-center justify-center gap-2"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Prepare for Scanning
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Import Scans Card - Admin Only */}
      {isAdmin && (
        <div className="bg-card border border-border rounded-xl p-6">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-green-500 to-emerald-500 flex items-center justify-center flex-shrink-0">
              <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-semibold mb-1">Import Scans to Database</h3>
              <p className="text-sm text-muted mb-4">
                Import CSV scan files into the database to update player statistics.
              </p>
              
              <button
                onClick={importScansFromFolder}
                disabled={importing}
                className="py-3 px-6 bg-green-500 hover:bg-green-600 disabled:bg-green-500/50 text-white font-semibold rounded-lg transition-colors flex items-center gap-2"
              >
                {importing ? (
                  <>
                    <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Importing...
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Import Scans from Server
                  </>
                )}
              </button>

              {/* Import Results */}
              {importResult && (
                <div className={`mt-4 p-4 rounded-lg border ${
                  importResult.status === "error" 
                    ? "bg-red-500/10 border-red-500/30" 
                    : importResult.new_imports && importResult.new_imports > 0
                    ? "bg-green-500/10 border-green-500/30"
                    : "bg-blue-500/10 border-blue-500/30"
                }`}>
                  {importResult.status === "error" ? (
                    <p className="text-red-400 text-sm">{importResult.folder}</p>
                  ) : (
                    <div className="space-y-2">
                      <div className="flex items-center gap-4 text-sm">
                        <span className="text-green-400">
                          <strong>{importResult.new_imports}</strong> new
                        </span>
                        <span className="text-blue-400">
                          <strong>{importResult.skipped}</strong> skipped
                        </span>
                        {importResult.errors ? (
                          <span className="text-red-400">
                            <strong>{importResult.errors}</strong> errors
                          </span>
                        ) : null}
                      </div>
                      {importResult.results && importResult.results.filter(r => r.status === "ok").length > 0 && (
                        <div className="text-xs text-muted">
                          Imported: {importResult.results.filter(r => r.status === "ok").map(r => r.file).join(", ")}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Scan Modal */}
      {showScanModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-bold">Configure Scan</h3>
              <button onClick={() => setShowScanModal(false)} className="text-muted hover:text-white">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">Scan Type</label>
                <div className="grid grid-cols-2 gap-2">
                  {(["kingdom", "alliance", "honor", "seed"] as ScanType[]).map((type) => (
                    <button
                      key={type}
                      onClick={() => setSelectedScanType(type)}
                      className={`py-2 px-3 rounded-lg border text-sm font-medium transition-colors capitalize ${
                        selectedScanType === type
                          ? "border-accent bg-accent/20 text-accent"
                          : "border-border hover:border-accent/50"
                      }`}
                    >
                      {type}
                    </button>
                  ))}
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-2">
                  Number of Governors
                </label>
                <input
                  type="number"
                  value={scanAmount}
                  onChange={(e) => setScanAmount(parseInt(e.target.value) || 1000)}
                  min={1}
                  max={10000}
                  className="w-full py-2 px-3 bg-bg border border-border rounded-lg focus:border-accent focus:outline-none"
                />
              </div>
              
              <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                <p className="text-sm text-yellow-400">
                  <strong>Important:</strong> Make sure the Rankings list is already open and visible in the game before clicking Start!
                </p>
              </div>
            </div>
            
            <div className="mt-6 flex gap-3">
              <button 
                onClick={() => setShowScanModal(false)} 
                className="flex-1 py-2 px-4 bg-border hover:bg-border/80 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => sendBotCommand("start_scan", selectedScanType, { amount: scanAmount })}
                disabled={sending}
                className="flex-1 py-2 px-4 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 text-white font-semibold rounded-lg transition-colors"
              >
                {sending ? "Starting..." : "Start Scan"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
