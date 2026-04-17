"use client";
import { useParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/lib/auth";

interface ScheduledTask {
  id: number;
  task_type: string;
  scan_type: string | null;
  interval_hours: number | null;
  enabled: boolean;
  last_run: string | null;
  next_run: string | null;
}

export default function SchedulesPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const { token, isOwner } = useAuth();
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // New task form
  const [taskType, setTaskType] = useState("scan");
  const [scanType, setScanType] = useState("kingdom");
  const [intervalHours, setIntervalHours] = useState(24);
  const [creating, setCreating] = useState(false);

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/schedules`);
      if (res.ok) setTasks(await res.json());
    } catch (err) {
      console.error("Failed to fetch schedules:", err);
    } finally {
      setLoading(false);
    }
  }, [apiBase, kdNum]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const handleCreate = async () => {
    setCreating(true);
    setMessage(null);
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/schedules`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          task_type: taskType,
          scan_type: taskType === "scan" ? scanType : null,
          interval_hours: intervalHours,
          enabled: true,
        }),
      });
      if (res.ok) {
        setMessage({ type: "success", text: "Schedule created" });
        fetchTasks();
      } else {
        const data = await res.json().catch(() => ({}));
        setMessage({ type: "error", text: data.detail || "Failed to create schedule" });
      }
    } catch {
      setMessage({ type: "error", text: "Failed to create schedule" });
    } finally {
      setCreating(false);
    }
  };

  const handleToggle = async (task: ScheduledTask) => {
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/schedules/${task.id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ enabled: !task.enabled }),
      });
      if (res.ok) fetchTasks();
    } catch (err) {
      console.error("Failed to toggle schedule:", err);
    }
  };

  const handleDelete = async (task: ScheduledTask) => {
    if (!confirm("Delete this scheduled task?")) return;
    try {
      const res = await fetch(`${apiBase}/kingdoms/${kdNum}/schedules/${task.id}`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        setMessage({ type: "success", text: "Schedule deleted" });
        fetchTasks();
      }
    } catch {
      setMessage({ type: "error", text: "Failed to delete schedule" });
    }
  };

  const formatTime = (iso: string | null) => {
    if (!iso || iso === "None") return "—";
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-accent">Scheduled Tasks</h1>
        <p className="text-muted">Automate recurring scans and bot operations</p>
      </div>

      {message && (
        <div className={`card ${message.type === "success" ? "border-green-500/50 text-green-400" : "border-red-500/50 text-red-400"}`}>
          {message.text}
        </div>
      )}

      {/* Create new schedule (owner only) */}
      {isOwner && (
        <div className="card">
          <h2 className="text-xl font-bold mb-4">New Schedule</h2>
          <div className="grid md:grid-cols-4 gap-4 items-end">
            <div>
              <label className="block text-sm text-muted mb-1">Type</label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value)}
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
              >
                <option value="scan">Scan</option>
                <option value="title_bot">Title Bot</option>
              </select>
            </div>
            {taskType === "scan" && (
              <div>
                <label className="block text-sm text-muted mb-1">Scan Type</label>
                <select
                  value={scanType}
                  onChange={(e) => setScanType(e.target.value)}
                  className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
                >
                  <option value="kingdom">Kingdom</option>
                  <option value="alliance">Alliance</option>
                  <option value="honor">Honor</option>
                  <option value="seed">Seed</option>
                </select>
              </div>
            )}
            <div>
              <label className="block text-sm text-muted mb-1">Interval (hours)</label>
              <input
                type="number"
                min={1}
                max={168}
                value={intervalHours}
                onChange={(e) => setIntervalHours(parseInt(e.target.value) || 24)}
                className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <button
                onClick={handleCreate}
                disabled={creating}
                className="w-full bg-accent hover:bg-accent/80 text-bg font-medium py-2 rounded-lg transition-colors disabled:opacity-50"
              >
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Task list */}
      <div className="card">
        <h2 className="text-xl font-bold mb-4">Active Schedules</h2>
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent" />
          </div>
        ) : tasks.length === 0 ? (
          <p className="text-center text-muted py-12">No scheduled tasks yet</p>
        ) : (
          <div className="space-y-3">
            {tasks.map((task) => (
              <div
                key={task.id}
                className={`flex items-center justify-between p-4 rounded-xl border ${
                  task.enabled ? "border-accent/30 bg-accent/5" : "border-border bg-bg/50 opacity-60"
                }`}
              >
                <div className="flex items-center gap-4">
                  <button
                    onClick={() => handleToggle(task)}
                    className={`w-12 h-6 rounded-full transition-colors relative ${
                      task.enabled ? "bg-accent" : "bg-border"
                    }`}
                  >
                    <div
                      className={`w-5 h-5 bg-white rounded-full absolute top-0.5 transition-transform ${
                        task.enabled ? "translate-x-6" : "translate-x-0.5"
                      }`}
                    />
                  </button>
                  <div>
                    <p className="font-bold capitalize">
                      {task.task_type === "scan" ? `${task.scan_type || "Kingdom"} Scan` : "Title Bot"}
                    </p>
                    <p className="text-sm text-muted">
                      Every {task.interval_hours}h
                      {task.next_run && task.next_run !== "None" ? ` · Next: ${formatTime(task.next_run)}` : ""}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <p className="text-xs text-muted">Last: {formatTime(task.last_run)}</p>
                  {isOwner && (
                    <button
                      onClick={() => handleDelete(task)}
                      className="text-red-400 hover:text-red-300 transition-colors"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
