"use client";
import { useParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useState } from "react";

export default function SettingsPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const { accessCode, isOwner } = useAuth();
  const [copiedLink, setCopiedLink] = useState(false);

  const isDemo = kingdom === "demo";

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
              <p className="text-muted text-sm">Download all kingdom data as CSV</p>
            </div>
            <button className="btn" disabled={isDemo}>
              Export CSV
            </button>
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

      {/* Danger Zone */}
      {!isDemo && (
        <div className="card border-red-500/30">
          <h3 className="font-semibold text-red-400 mb-4">Danger Zone</h3>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Reset Password</p>
              <p className="text-muted text-sm">Generate a new password for this kingdom</p>
            </div>
            <button className="px-4 py-2 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors">
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Help */}
      <div className="card bg-accent/5 border-accent/20">
        <h3 className="font-semibold mb-3">Need Help?</h3>
        <p className="text-muted text-sm mb-4">
          If you have questions or need assistance, check out our documentation or contact support.
        </p>
        <div className="flex gap-3">
          <button className="btn">Documentation</button>
          <button className="px-4 py-2 rounded-lg border border-border hover:border-accent transition-colors">
            Contact Support
          </button>
        </div>
      </div>
    </div>
  );
}
