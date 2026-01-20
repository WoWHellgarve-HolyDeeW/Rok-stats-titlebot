"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";

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

const TITLE_INFO: Record<string, { name: string; buff: string; color: string; icon: string; slots: number }> = {
  scientist: { name: "Scientist", buff: "+5% Research Speed", color: "blue", icon: "🔬", slots: 2 },
  architect: { name: "Architect", buff: "+5% Building Speed", color: "amber", icon: "🏗️", slots: 2 },
  duke: { name: "Duke", buff: "+10% Gathering Speed", color: "green", icon: "⚒️", slots: 2 },
  justice: { name: "Justice", buff: "+5% Troop Attack", color: "red", icon: "⚔️", slots: 1 },
};

export default function TitlesPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const [queue, setQueue] = useState<TitleRequest[]>([]);
  const [stats, setStats] = useState<TitleStats | null>(null);
  const [loading, setLoading] = useState(true);
  
  // Bot settings
  const [botAllianceTag, setBotAllianceTag] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const fetchQueue = useCallback(async () => {
    try {
      const [queueRes, statsRes] = await Promise.all([
        fetch(`${apiBase}/kingdoms/${kdNum}/titles/queue`),
        fetch(`${apiBase}/kingdoms/${kdNum}/titles/stats`),
      ]);
      
      if (queueRes.ok) setQueue(await queueRes.json());
      if (statsRes.ok) setStats(await statsRes.json());
    } catch (err) {
      console.error("Failed to fetch queue:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBase, kdNum]);

  const fetchSettings = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/titles/settings`);
      if (!res.ok) return;
      const data = await res.json();
      setBotAllianceTag((data?.bot_alliance_tag || "").toString());
    } catch (err) {
      console.error("Failed to fetch title bot settings:", err);
    }
  }, [apiBase, kdNum]);

  useEffect(() => {
    fetchQueue();
    fetchSettings();
    const interval = setInterval(fetchQueue, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, [fetchQueue, fetchSettings]);

  const handleSaveSettings = async () => {
    setSavingSettings(true);
    setMessage(null);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/titles/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_alliance_tag: botAllianceTag.trim() ? botAllianceTag.trim().toUpperCase() : null,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setMessage({ type: "error", text: data.detail || "Failed to save settings" });
        return;
      }

      setBotAllianceTag((data?.bot_alliance_tag || "").toString());
      setMessage({ type: "success", text: "Bot settings saved" });
    } catch (err) {
      setMessage({ type: "error", text: "Failed to save settings" });
    } finally {
      setSavingSettings(false);
    }
  };

  const handleClearQueue = async () => {
    if (!confirm("Are you sure you want to clear ALL pending requests? This cannot be undone.")) {
      return;
    }
    
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/titles/queue/clear?status=all`, {
        method: "DELETE",
      });
      
      const data = await res.json();
      if (res.ok) {
        setMessage({ type: "success", text: `Cleared ${data.cleared} requests from queue` });
        fetchQueue();
      } else {
        setMessage({ type: "error", text: data.detail || "Failed to clear queue" });
      }
    } catch (err) {
      setMessage({ type: "error", text: "Failed to clear queue" });
    }
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-accent">Title Bot</h1>
        <p className="text-muted">Request titles for your account - automated by our bot</p>
      </div>

      {/* Bot Settings */}
      <div className="card">
        <h2 className="text-xl font-bold mb-4">Bot Settings</h2>
        <div className="grid md:grid-cols-3 gap-4 items-end">
          <div>
            <label className="block text-sm text-muted mb-1">Bot Alliance Tag</label>
            <input
              type="text"
              value={botAllianceTag}
              onChange={(e) => setBotAllianceTag(e.target.value.toUpperCase().slice(0, 10))}
              placeholder="e.g., F28A"
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
            />
          </div>
          <div>
            <button
              type="button"
              onClick={handleSaveSettings}
              disabled={savingSettings}
              className="w-full bg-accent hover:bg-accent/80 text-bg font-medium py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              {savingSettings ? "Saving..." : "Save Settings"}
            </button>
          </div>
          <div>
            <button
              type="button"
              onClick={handleClearQueue}
              className="w-full bg-red-600 hover:bg-red-700 text-white font-medium py-2 rounded-lg transition-colors"
            >
              🗑️ Clear Queue
            </button>
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="card bg-gradient-to-br from-yellow-900/50 to-yellow-800/30 border-yellow-500/30">
            <p className="text-xs text-yellow-300 uppercase tracking-wider mb-1">Queue</p>
            <p className="text-2xl font-bold text-white">{stats.pending}</p>
          </div>
          <div className="card bg-gradient-to-br from-blue-900/50 to-blue-800/30 border-blue-500/30">
            <p className="text-xs text-blue-300 uppercase tracking-wider mb-1">In Progress</p>
            <p className="text-2xl font-bold text-white">{stats.assigned}</p>
          </div>
          <div className="card bg-gradient-to-br from-green-900/50 to-green-800/30 border-green-500/30">
            <p className="text-xs text-green-300 uppercase tracking-wider mb-1">Done Today</p>
            <p className="text-2xl font-bold text-white">{stats.completed_today}</p>
          </div>
          <div className="card bg-gradient-to-br from-purple-900/50 to-purple-800/30 border-purple-500/30">
            <p className="text-xs text-purple-300 uppercase tracking-wider mb-1">Wait Time</p>
            <p className="text-2xl font-bold text-white">~{stats.queue_position_estimate_minutes} min</p>
          </div>
        </div>
      )}

      {/* Message */}
      {message && (
        <div className={`p-3 rounded-lg ${message.type === "success" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
          {message.text}
        </div>
      )}

      {/* Live Queue */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold">📋 Live Queue</h2>
          <span className="text-xs text-muted">Auto-refreshes every 10s</span>
        </div>

        {loading ? (
          <div className="text-center py-8 text-muted">
            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
            Loading...
          </div>
        ) : queue.length === 0 ? (
          <div className="text-center py-8 text-muted">
            <p className="mb-2">No pending requests</p>
            <p className="text-sm">Titles are requested in-game via alliance chat</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-[500px] overflow-y-auto">
            {queue.map((req, idx) => (
              <div
                key={req.id}
                className={`flex items-center gap-3 p-3 rounded-lg ${
                    req.status === "assigned" ? "bg-blue-500/10 border border-blue-500/30" : "bg-bg"
                  }`}
                >
                  <div className="w-8 h-8 flex items-center justify-center rounded-full bg-border text-sm font-bold">
                    {idx + 1}
                  </div>
                  <span className="text-xl">{TITLE_INFO[req.title_type]?.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{req.governor_name}</p>
                    <div className="flex items-center gap-2 text-xs text-muted">
                      {req.alliance_tag && <span>[{req.alliance_tag}]</span>}
                      <span>{TITLE_INFO[req.title_type]?.name}</span>
                    </div>
                  </div>
                  {getStatusBadge(req.status)}
                </div>
              ))}
            </div>
          )}
        </div>

      {/* Info Section */}
      <div className="card bg-gradient-to-r from-blue-900/20 to-purple-900/20 border-blue-500/20">
        <h3 className="font-bold mb-2">ℹ️ How to Request a Title</h3>
        <ul className="text-sm text-muted space-y-1">
          <li>• Open alliance chat in-game and type your request</li>
          <li>• The bot will pick up your message and add you to the queue</li>
          <li>• Requests are processed in order (first come, first served)</li>
          <li>• Titles last for 24 hours and can be renewed</li>
          <li>• <strong>Note:</strong> You must be in an alliance where the bot is R4/R5</li>
        </ul>
      </div>
    </div>
  );
}
