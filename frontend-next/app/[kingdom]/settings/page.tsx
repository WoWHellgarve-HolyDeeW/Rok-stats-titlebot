"use client";
import { useParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useEffect, useState } from "react";

interface WarPeriod {
  index: number;
  label: string;
  start: string | null;
  end: string | null;
  configured: boolean;
}

interface KvKSettings {
  kvk_active: string | null;
  kvk_start: string | null;
  kvk_end: string | null;
  war1_start: string | null;
  war1_end: string | null;
  war2_start: string | null;
  war2_end: string | null;
  war3_start: string | null;
  war3_end: string | null;
  war_periods: WarPeriod[];
}

export default function SettingsPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const { accessCode, isOwner, token } = useAuth();
  const [copiedLink, setCopiedLink] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [kvkSettings, setKvkSettings] = useState<KvKSettings>({
    kvk_active: null,
    kvk_start: null,
    kvk_end: null,
    war1_start: null,
    war1_end: null,
    war2_start: null,
    war2_end: null,
    war3_start: null,
    war3_end: null,
    war_periods: [],
  });
  const [kvkSaving, setKvkSaving] = useState(false);
  const [kvkMessage, setKvkMessage] = useState<string | null>(null);

  const isDemo = kingdom === "demo";
  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  const toInputValue = (value: string | null | undefined) => value ? value.slice(0, 16) : "";

  useEffect(() => {
    if (isDemo) return;
    const fetchKvkSettings = async () => {
      try {
        const res = await fetch(`${apiBase}/kingdoms/${kdNum}/kvk-settings`);
        if (!res.ok) return;
        setKvkSettings(await res.json());
      } catch {
        // ignore
      }
    };
    fetchKvkSettings();
  }, [apiBase, isDemo, kdNum]);

  const getShareLink = () => {
    if (typeof window === "undefined") return "";
    return `${window.location.origin}/${kingdom}/home?code=${accessCode}`;
  };

  const copyShareLink = () => {
    const link = getShareLink();
    if (link) {
      navigator.clipboard.writeText(link);
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2000);
    }
  };

  const handleExport = async (type: "current" | "history") => {
    setExporting(true);
    try {
      const endpoint = type === "history"
        ? `${apiBase}/kingdoms/${kdNum}/export/history`
        : `${apiBase}/kingdoms/${kdNum}/export`;
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `kingdom_${kdNum}_${type}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Export failed. Please try again.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-muted">Configure your kingdom dashboard</p>
      </div>

      {isDemo && (
        <div className="bg-amber-500/20 border border-amber-500/50 text-amber-400 px-4 py-3 rounded-lg">
          <strong>Demo Mode:</strong> Settings are not available in demo mode. Log in with your kingdom to access settings.
        </div>
      )}

      {/* Access Code - Only show to owners (login with password) */}
      {!isDemo && accessCode && isOwner && (
        <div className="card">
          <h3 className="font-semibold mb-4">🔗 Share Access with Alliance</h3>
          <p className="text-muted text-sm mb-4">
            Share this link with alliance members to give them read-only access to the kingdom dashboard.
          </p>
          
          {/* Share Link */}
          <div>
            <label className="block text-xs text-muted mb-2 uppercase tracking-wider">Share Link (give this to players)</label>
            <div className="flex items-center gap-3">
              <code className="flex-1 bg-bg px-4 py-3 rounded-lg font-mono text-sm text-accent break-all">
                {getShareLink()}
              </code>
              <button
                onClick={copyShareLink}
                className="btn whitespace-nowrap"
              >
                {copiedLink ? "✓ Copied!" : "Copy Link"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Data Management */}
      <div className="card">
        <h3 className="font-semibold mb-4">Data Management</h3>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Export Data</p>
              <p className="text-muted text-sm">Download kingdom data as CSV</p>
            </div>
            <div className="flex gap-2">
              <button
                className="btn"
                disabled={isDemo || exporting}
                onClick={() => handleExport("current")}
              >
                {exporting ? "Exporting…" : "📋 Latest Scan"}
              </button>
              <button
                className="px-4 py-2 rounded-lg border border-border hover:border-accent transition-colors text-sm"
                disabled={isDemo || exporting}
                onClick={() => handleExport("history")}
              >
                📊 Full History
              </button>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">API Access</p>
              <p className="text-muted text-sm">Access kingdom data via API</p>
            </div>
            <code className="text-sm bg-bg px-3 py-2 rounded">
              /kingdoms/{kingdom}/governors
            </code>
          </div>
        </div>
      </div>

      {!isDemo && isOwner && (
        <div className="card">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h3 className="font-semibold">KvK Windows</h3>
              <p className="text-muted text-sm">Configure the full KvK span and the specific War 1/2/3 windows. The KD dashboard and KvK page use only the war windows when they are configured.</p>
            </div>
            {kvkMessage && <span className="text-xs px-3 py-1 rounded-full bg-green-500/20 text-green-400">{kvkMessage}</span>}
          </div>

          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <label className="block text-xs text-muted mb-1 uppercase tracking-wider">KvK Code</label>
                <input type="text" value={kvkSettings.kvk_active || ""} onChange={(e) => setKvkSettings({ ...kvkSettings, kvk_active: e.target.value || null })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent" placeholder="e.g. c12949" />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1 uppercase tracking-wider">KvK Start</label>
                <input type="datetime-local" value={toInputValue(kvkSettings.kvk_start)} onChange={(e) => setKvkSettings({ ...kvkSettings, kvk_start: e.target.value || null })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent" />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1 uppercase tracking-wider">KvK End</label>
                <input type="datetime-local" value={toInputValue(kvkSettings.kvk_end)} onChange={(e) => setKvkSettings({ ...kvkSettings, kvk_end: e.target.value || null })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent" />
              </div>
            </div>

            {[1, 2, 3].map((warIndex) => (
              <div key={warIndex} className="rounded-xl border border-border p-4">
                <h4 className="font-medium mb-3">War {warIndex}</h4>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="block text-xs text-muted mb-1 uppercase tracking-wider">Start</label>
                    <input type="datetime-local" value={toInputValue(kvkSettings[`war${warIndex}_start` as keyof KvKSettings] as string | null)} onChange={(e) => setKvkSettings({ ...kvkSettings, [`war${warIndex}_start`]: e.target.value || null })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent" />
                  </div>
                  <div>
                    <label className="block text-xs text-muted mb-1 uppercase tracking-wider">End</label>
                    <input type="datetime-local" value={toInputValue(kvkSettings[`war${warIndex}_end` as keyof KvKSettings] as string | null)} onChange={(e) => setKvkSettings({ ...kvkSettings, [`war${warIndex}_end`]: e.target.value || null })} className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent" />
                  </div>
                </div>
              </div>
            ))}

            <div className="flex justify-end">
              <button
                className="btn disabled:opacity-50"
                disabled={!token || kvkSaving}
                onClick={async () => {
                  if (!token) return;
                  setKvkSaving(true);
                  setKvkMessage(null);
                  try {
                    const res = await fetch(`${apiBase}/kingdoms/${kdNum}/kvk-settings`, {
                      method: "PUT",
                      headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${token}`,
                      },
                      body: JSON.stringify({
                        kvk_code: kvkSettings.kvk_active,
                        kvk_start: kvkSettings.kvk_start,
                        kvk_end: kvkSettings.kvk_end,
                        war1_start: kvkSettings.war1_start,
                        war1_end: kvkSettings.war1_end,
                        war2_start: kvkSettings.war2_start,
                        war2_end: kvkSettings.war2_end,
                        war3_start: kvkSettings.war3_start,
                        war3_end: kvkSettings.war3_end,
                      }),
                    });
                    if (!res.ok) {
                      const payload = await res.json().catch(() => ({ detail: "Failed to save KvK settings" }));
                      throw new Error(payload.detail || "Failed to save KvK settings");
                    }
                    setKvkSettings(await res.json());
                    setKvkMessage("Saved");
                  } catch (err) {
                    setKvkMessage(err instanceof Error ? err.message : "Failed to save KvK settings");
                  } finally {
                    setKvkSaving(false);
                  }
                }}
              >
                {kvkSaving ? "Saving…" : "Save KvK Windows"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Danger Zone */}
      {!isDemo && isOwner && (
        <div className="card border-red-500/30">
          <h3 className="font-semibold text-red-400 mb-4">Danger Zone</h3>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Reset Password</p>
              <p className="text-muted text-sm">Generate a new password for this kingdom</p>
            </div>
            <button
              className="px-4 py-2 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors disabled:opacity-50"
              disabled={resetting}
              onClick={async () => {
                if (!confirm("Are you sure? This will generate a new password and invalidate the current one.")) return;
                setResetting(true);
                try {
                  const res = await fetch(`${apiBase}/admin/kingdoms/${kdNum}/reset-password`, {
                    method: "POST",
                    headers: { Authorization: `Bearer ${accessCode}` },
                  });
                  if (res.ok) {
                    const data = await res.json();
                    alert(`New password: ${data.password}\n\nSave this — you will need it to log in.`);
                  } else {
                    const err = await res.json().catch(() => ({}));
                    alert(err.detail || "Failed to reset password. Admin access required.");
                  }
                } catch {
                  alert("Failed to connect to server.");
                } finally {
                  setResetting(false);
                }
              }}
            >
              {resetting ? "Resetting…" : "Reset"}
            </button>
          </div>
        </div>
      )}

    </div>
  );
}
