"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";

interface BotLog {
  id: number;
  action: string;
  detail: string | null;
  governor_name: string | null;
  title_type: string | null;
  level: string;
  created_at: string;
}

const ACTION_COLORS: Record<string, string> = {
  title_given: "text-green-400",
  title_failed: "text-red-400",
  mode_change: "text-blue-400",
  scan_started: "text-cyan-400",
  scan_completed: "text-emerald-400",
  error: "text-red-500",
};

const LEVEL_BADGE: Record<string, string> = {
  info: "bg-blue-500/20 text-blue-400",
  warn: "bg-yellow-500/20 text-yellow-400",
  error: "bg-red-500/20 text-red-400",
};

export default function BotLogsPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const [logs, setLogs] = useState<BotLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("");

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const fetchLogs = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (filter) params.set("action", filter);
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/bot/logs?${params}`);
      if (res.ok) setLogs(await res.json());
    } catch (err) {
      console.error("Failed to fetch bot logs:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBase, kdNum, filter]);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 15000);
    return () => clearInterval(interval);
  }, [fetchLogs]);

  const formatTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch {
      return iso;
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-accent">Bot Logs</h1>
        <p className="text-muted">History of bot actions, title assignments, and errors</p>
      </div>

      {/* Filter */}
      <div className="card">
        <div className="flex flex-wrap gap-2">
          {["", "title_given", "title_failed", "mode_change", "error"].map((f) => (
            <button
              key={f}
              onClick={() => { setFilter(f); setLoading(true); }}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                filter === f
                  ? "bg-accent text-bg"
                  : "bg-bg border border-border hover:border-accent/50"
              }`}
            >
              {f || "All"}
            </button>
          ))}
        </div>
      </div>

      {/* Log table */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent" />
          </div>
        ) : logs.length === 0 ? (
          <p className="text-center text-muted py-12">No log entries found</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted">
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Level</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Detail</th>
                  <th className="px-4 py-3">Governor</th>
                  <th className="px-4 py-3">Title</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b border-border/50 hover:bg-bg/50">
                    <td className="px-4 py-3 text-xs text-muted whitespace-nowrap">
                      {formatTime(log.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${LEVEL_BADGE[log.level] || LEVEL_BADGE.info}`}>
                        {log.level.toUpperCase()}
                      </span>
                    </td>
                    <td className={`px-4 py-3 font-mono text-xs ${ACTION_COLORS[log.action] || "text-gray-400"}`}>
                      {log.action}
                    </td>
                    <td className="px-4 py-3 text-sm max-w-xs truncate">
                      {log.detail || "—"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {log.governor_name || "—"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {log.title_type ? (
                        <span className="capitalize">{log.title_type}</span>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
