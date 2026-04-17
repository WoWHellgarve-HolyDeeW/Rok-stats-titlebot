"use client";
import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@/lib/auth";

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

export default function FinderPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const { token, isAuthenticated, kingdom: authKingdom } = useAuth();
  const isAdmin = isAuthenticated && authKingdom === parseInt(kingdom);

  const [govId, setGovId] = useState("");
  const [finderStatus, setFinderStatus] = useState<FinderStatus>({ status: "no_request" });
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  const pollFinderStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/find-player`);
      if (res.ok) {
        const data = await res.json();
        setFinderStatus(data);
        if (data.status === "found" || data.status === "not_found" || data.status === "error") {
          setSearching(false);
        }
      }
    } catch { /* ignore */ }
  }, [API_URL, kingdom]);

  // Poll while searching
  useEffect(() => {
    if (!searching) return;
    const interval = setInterval(pollFinderStatus, 2000);
    return () => clearInterval(interval);
  }, [searching, pollFinderStatus]);

  // Fetch status on page load (in case search is already in progress)
  useEffect(() => {
    pollFinderStatus().then(() => {
      // If status is "searching", re-enable polling
      setFinderStatus(prev => {
        if (prev.status === "searching") setSearching(true);
        return prev;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startSearch = async () => {
    const id = parseInt(govId);
    if (!id || id <= 0) {
      setError("Enter a valid Governor ID");
      return;
    }
    setError(null);
    setSearching(true);
    setFinderStatus({ status: "searching", progress: "Sending request..." });

    try {
      const params = new URLSearchParams({ governor_id: String(id) });
      const res = await fetch(`${API_URL}/kingdoms/${kingdom}/bot/find-player?${params}`, {
        method: "POST",
        headers: token ? { "Authorization": `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setError(err.detail || "Request failed");
        setSearching(false);
        return;
      }
      // Start polling
      pollFinderStatus();
    } catch (e) {
      setError(String(e));
      setSearching(false);
    }
  };

  const formatShieldTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h >= 24) {
      const d = Math.floor(h / 24);
      return `${d}d ${h % 24}h ${m}m`;
    }
    return `${h}h ${m}m`;
  };

  const result = finderStatus.result;
  const isSearching = finderStatus.status === "searching";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Player Finder</h1>
        <p className="text-muted text-sm">
          Search for a governor&apos;s city on the map — get shield status, coordinates, and linked accounts
        </p>
      </div>

      {/* Search Card */}
      <div className="bg-card border border-border rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-4">Search Governor</h2>
        <div className="flex gap-3">
          <input
            type="number"
            placeholder="Enter Governor ID"
            value={govId}
            onChange={(e) => setGovId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !searching && startSearch()}
            disabled={isSearching}
            className="flex-1 px-4 py-2.5 bg-background border border-border rounded-lg
                       text-foreground placeholder:text-muted focus:outline-none focus:ring-2
                       focus:ring-accent/50 disabled:opacity-50"
          />
          <button
            onClick={startSearch}
            disabled={isSearching || !govId}
            className="px-6 py-2.5 bg-accent text-white rounded-lg font-medium
                       hover:bg-accent/80 disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors flex items-center gap-2"
          >
            {isSearching ? (
              <>
                <span className="animate-spin">⏳</span>
                Searching...
              </>
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                Find
              </>
            )}
          </button>
        </div>
        {error && (
          <p className="mt-2 text-red-400 text-sm">{error}</p>
        )}
      </div>

      {/* Progress */}
      {isSearching && (
        <div className="bg-card border border-border rounded-xl p-6">
          <div className="flex items-center gap-3">
            <div className="animate-spin w-6 h-6 border-2 border-accent border-t-transparent rounded-full" />
            <div>
              <p className="font-medium">Searching...</p>
              <p className="text-sm text-muted">{finderStatus.progress || "Bot is navigating the map..."}</p>
            </div>
          </div>
        </div>
      )}

      {/* Results */}
      {finderStatus.status === "found" && result && (
        <div className="space-y-4">
          {/* Location Card */}
          <div className="bg-card border border-border rounded-xl p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-green-500/20 rounded-lg flex items-center justify-center text-xl">
                📍
              </div>
              <div>
                <h2 className="text-lg font-semibold">
                  {result.governor_name}
                  {result.alliance_tag && (
                    <span className="text-sm text-muted ml-2">[{result.alliance_tag}]</span>
                  )}
                </h2>
                <p className="text-sm text-muted">Governor ID: {result.governor_id}</p>
              </div>
              {result.fighting && (
                <span className="ml-auto px-2 py-1 bg-red-500/20 text-red-400 text-xs font-bold rounded">
                  IN COMBAT
                </span>
              )}
            </div>

            {/* Row 1: Location & Shield */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">Coordinates</p>
                <p className="font-mono font-bold">
                  {result.x > 0 || result.y > 0
                    ? `X:${result.x} Y:${result.y}`
                    : "Unknown"}
                </p>
              </div>
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">Shield Status</p>
                <p className={`font-bold ${
                  result.shield_remaining_seconds && result.shield_remaining_seconds > 0
                    ? "text-blue-400" : "text-red-400"
                }`}>
                  {result.shield_remaining_seconds && result.shield_remaining_seconds > 0
                    ? `🛡️ ${formatShieldTime(result.shield_remaining_seconds)}`
                    : "⚔️ No Shield"}
                </p>
              </div>
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">City Level</p>
                <p className="font-bold">{result.city_level || "—"}</p>
              </div>
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">Temple Title</p>
                <p className="font-bold">{result.temple_title || "—"}</p>
              </div>
            </div>

            {/* Row 2: Power & Kill Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">Power</p>
                <p className="font-bold text-yellow-400">
                  {result.power ? result.power.toLocaleString() : "—"}
                </p>
              </div>
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">Kill Count</p>
                <p className="font-bold text-red-400">
                  {result.kill ? result.kill.toLocaleString() : "—"}
                </p>
              </div>
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">Kill Score</p>
                <p className="font-bold">
                  {result.kill_score ? result.kill_score.toLocaleString() : "—"}
                </p>
              </div>
              <div className="bg-background p-3 rounded-lg">
                <p className="text-xs text-muted mb-1">Alliance</p>
                <p className="font-bold">
                  {result.alliance_name
                    ? `${result.alliance_tag ? `[${result.alliance_tag}] ` : ""}${result.alliance_name}`
                    : result.alliance_tag || "—"}
                </p>
              </div>
            </div>
          </div>

          {/* Linked Accounts */}
          {result.linked_accounts && result.linked_accounts.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-6">
              <h3 className="font-semibold mb-3">Linked Accounts</h3>
              <div className="space-y-2">
                {result.linked_accounts.map((acc, i) => (
                  <div key={i} className="flex items-center gap-3 bg-background p-3 rounded-lg">
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm ${
                      acc.is_main ? "bg-yellow-500/20 text-yellow-400" : "bg-zinc-700/30 text-muted"
                    }`}>
                      {acc.is_main ? "👑" : "🏠"}
                    </div>
                    <div>
                      <p className="font-medium">{acc.governor_name || `ID: ${acc.governor_id}`}</p>
                      <p className="text-xs text-muted">
                        Gov ID: {acc.governor_id} • {acc.is_main ? "Main Account" : "Farm Account"}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Not Found */}
      {finderStatus.status === "not_found" && (
        <div className="bg-card border border-yellow-500/30 rounded-xl p-6">
          <div className="flex items-center gap-3">
            <span className="text-2xl">⚠️</span>
            <div>
              <p className="font-medium">Governor Not Found</p>
              <p className="text-sm text-muted">
                {finderStatus.progress || "Could not locate this governor on the map. They may be in a different kingdom or the search failed."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {finderStatus.status === "error" && (
        <div className="bg-card border border-red-500/30 rounded-xl p-6">
          <div className="flex items-center gap-3">
            <span className="text-2xl">❌</span>
            <div>
              <p className="font-medium">Search Error</p>
              <p className="text-sm text-muted">
                {finderStatus.progress || "An error occurred during the search."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Info Card */}
      <div className="bg-card border border-border rounded-xl p-6">
        <h3 className="font-semibold mb-2">How it works</h3>
        <ol className="list-decimal list-inside space-y-1 text-sm text-muted">
          <li>Enter the Governor ID of the player you want to find</li>
          <li>The bot navigates to the in-game search and locates their city</li>
          <li>Shield status, coordinates, and linked accounts are captured</li>
          <li>Results appear here automatically when the search is complete</li>
        </ol>
        <p className="mt-3 text-xs text-muted">
          Note: The bot must be connected and idle for this to work. Shield detection uses Frida hooks.
          Linked accounts are based on previously scanned data (same OpenUid = same account owner).
        </p>
      </div>
    </div>
  );
}
