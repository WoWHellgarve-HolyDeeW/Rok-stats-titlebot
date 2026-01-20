"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAdmin } from "@/lib/admin";
import Link from "next/link";

interface Kingdom {
  id: number;
  number: number;
  name: string | null;
  has_password: boolean;
  access_code: string | null;
  governors_count: number;
  kvk_active: string | null;
}

interface NewKingdomResult {
  kingdom: number;
  name: string | null;
  password: string;
  access_code: string;
}

export default function AdminDashboardPage() {
  const router = useRouter();
  const { token, username, isSuper, logout, isAuthenticated, isLoading } = useAdmin();
  
  const [kingdoms, setKingdoms] = useState<Kingdom[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newKingdom, setNewKingdom] = useState({ number: "", name: "" });
  const [createdKingdom, setCreatedKingdom] = useState<NewKingdomResult | null>(null);
  const [resetResult, setResetResult] = useState<{ kingdom: number; password: string } | null>(null);
  const [error, setError] = useState("");

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/admin");
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    if (token) {
      fetchKingdoms();
    }
  }, [token]);

  const fetchKingdoms = async () => {
    try {
      const res = await fetch(`${apiBase}/admin/kingdoms`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setKingdoms(data);
      }
    } catch (err) {
      console.error("Failed to fetch kingdoms:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setCreatedKingdom(null);

    console.log("[admin] create kingdom ->", newKingdom, "api:", `${apiBase}/admin/kingdoms`);

    const kingdomNumber = parseInt(newKingdom.number, 10);
    if (Number.isNaN(kingdomNumber)) {
      setError("Please enter a valid kingdom number");
      return;
    }

    try {
      const res = await fetch(`${apiBase}/admin/kingdoms`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          kingdom: kingdomNumber,
          name: newKingdom.name || null,
        }),
      });

      console.log("[admin] create status", res.status);
      if (res.ok) {
        const data = await res.json();
        setCreatedKingdom(data);
        setNewKingdom({ number: "", name: "" });
        fetchKingdoms();
      } else {
        let detail = "Failed to create kingdom";
        try {
          const err = await res.json();
          if (err?.detail) detail = err.detail;
        } catch {
          const txt = await res.text();
          if (txt) detail = txt;
        }
        console.error("[admin] create error", detail);
        setError(detail);
      }
    } catch (err) {
      console.error("[admin] create exception", err);
      setError("Failed to create kingdom");
    }
  };

  const handleResetPassword = async (kingdomNumber: number) => {
    if (!confirm(`Reset password for Kingdom ${kingdomNumber}?`)) return;

    try {
      const res = await fetch(`${apiBase}/admin/kingdoms/${kingdomNumber}/reset-password`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.ok) {
        const data = await res.json();
        setResetResult({ kingdom: kingdomNumber, password: data.password });
      }
    } catch (err) {
      console.error("Failed to reset password:", err);
    }
  };

  const handleDelete = async (kingdomNumber: number) => {
    if (!confirm(`Delete Kingdom ${kingdomNumber}? This cannot be undone.`)) return;
    setError("");
    try {
      const res = await fetch(`${apiBase}/admin/kingdoms/${kingdomNumber}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        fetchKingdoms();
      } else {
        let detail = "Failed to delete kingdom";
        try {
          const err = await res.json();
          if (err?.detail) detail = err.detail;
        } catch {
          const txt = await res.text();
          if (txt) detail = txt;
        }
        setError(detail);
      }
    } catch (err) {
      setError("Failed to delete kingdom");
    }
  };

  const handleLogout = () => {
    logout();
    router.push("/admin");
  };

  if (isLoading || !isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-accent"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-border bg-card">
        <div className="container flex items-center justify-between py-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <span className="text-xl font-bold">Admin Panel</span>
              <span className="text-muted text-sm ml-2">({username})</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/" className="text-muted hover:text-fg text-sm">
              View Site
            </Link>
            <button onClick={handleLogout} className="text-red-400 hover:text-red-300 text-sm">
              Logout
            </button>
          </div>
        </div>
      </header>

      <main className="container py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">Kingdom Management</h1>
            <p className="text-muted">Create and manage kingdom accounts</p>
          </div>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="btn"
          >
            {showCreate ? "Cancel" : "+ New Kingdom"}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-500/20 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        {/* Created Kingdom Result */}
        {createdKingdom && (
          <div className="bg-green-500/20 border border-green-500/50 text-green-400 px-4 py-4 rounded-lg mb-6">
            <h3 className="font-bold mb-2">✅ Kingdom Created Successfully!</h3>
            <div className="bg-bg rounded p-4 text-fg">
              <p><strong>Kingdom:</strong> {createdKingdom.kingdom}</p>
              <p><strong>Name:</strong> {createdKingdom.name || "—"}</p>
              <p><strong>Password:</strong> <code className="bg-card px-2 py-1 rounded text-accent">{createdKingdom.password}</code></p>
              <p><strong>Share Link:</strong> <code className="bg-card px-2 py-1 rounded text-accent break-all">{typeof window !== "undefined" ? `${window.location.origin}/${createdKingdom.kingdom}/home?code=${createdKingdom.access_code}` : ""}</code></p>
              <p className="text-amber-400 text-sm mt-2">⚠️ Save this password! It won&apos;t be shown again.</p>
            </div>
          </div>
        )}

        {/* Reset Password Result */}
        {resetResult && (
          <div className="bg-blue-500/20 border border-blue-500/50 text-blue-400 px-4 py-4 rounded-lg mb-6">
            <h3 className="font-bold mb-2">🔑 Password Reset for Kingdom {resetResult.kingdom}</h3>
            <p>New Password: <code className="bg-card px-2 py-1 rounded text-accent">{resetResult.password}</code></p>
            <button onClick={() => setResetResult(null)} className="text-sm underline mt-2">Dismiss</button>
          </div>
        )}

        {/* Create Form */}
        {showCreate && (
          <div className="card mb-6">
            <h3 className="text-lg font-semibold mb-4">Create New Kingdom</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-muted mb-1">Kingdom Number *</label>
                  <input
                    type="number"
                    value={newKingdom.number}
                    onChange={(e) => setNewKingdom({ ...newKingdom, number: e.target.value })}
                    placeholder="e.g. 3328"
                    className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm text-muted mb-1">Kingdom Name (optional)</label>
                  <input
                    type="text"
                    value={newKingdom.name}
                    onChange={(e) => setNewKingdom({ ...newKingdom, name: e.target.value })}
                    placeholder="e.g. Iron Throne"
                    className="w-full bg-bg border border-border rounded-lg px-3 py-2 focus:outline-none focus:border-accent"
                  />
                </div>
              </div>
              <button type="submit" className="btn">
                Create Kingdom
              </button>
            </form>
          </div>
        )}

        {/* Kingdoms List */}
        <div className="card overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-bg">
                  <th className="text-left px-4 py-3 font-medium">Kingdom</th>
                  <th className="text-left px-4 py-3 font-medium">Name</th>
                  <th className="text-right px-4 py-3 font-medium">Players</th>
                  <th className="text-center px-4 py-3 font-medium">Status</th>
                  <th className="text-right px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={5} className="text-center py-12 text-muted">
                      <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
                      Loading...
                    </td>
                  </tr>
                ) : kingdoms.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="text-center py-12 text-muted">
                      No kingdoms yet. Create your first kingdom!
                    </td>
                  </tr>
                ) : (
                  kingdoms.map((k) => (
                    <tr key={k.id} className="border-b border-border hover:bg-border/50">
                      <td className="px-4 py-3 font-bold">{k.number}</td>
                      <td className="px-4 py-3">{k.name || "—"}</td>
                      <td className="px-4 py-3 text-right">{k.governors_count}</td>
                      <td className="px-4 py-3 text-center">
                        {k.has_password ? (
                          <span className="px-2 py-1 bg-green-500/20 text-green-400 rounded text-xs">Active</span>
                        ) : (
                          <span className="px-2 py-1 bg-amber-500/20 text-amber-400 rounded text-xs">No Password</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => handleResetPassword(k.number)}
                          className="text-accent hover:underline text-xs mr-3"
                        >
                          Reset Password
                        </button>
                        {isSuper && (
                          <button
                            onClick={() => handleDelete(k.number)}
                            className="text-red-400 hover:underline text-xs mr-3"
                          >
                            Delete
                          </button>
                        )}
                        <Link
                          href={`/${k.number}/home`}
                          className="text-muted hover:text-fg text-xs"
                        >
                          View →
                        </Link>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}
