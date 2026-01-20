"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

interface Alliance {
  alliance: string;
  member_count: number;
  total_power: number;
  total_kills: number;
  avg_power: number;
}

export default function AlliancesPage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const [loading, setLoading] = useState(true);
  const [alliances, setAlliances] = useState<Alliance[]>([]);
  const [sortBy, setSortBy] = useState("total_power");
  const [sortDir, setSortDir] = useState("desc");

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();
  const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);

  useEffect(() => {
    const fetchAlliances = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${apiBase}/kingdoms/${kdNum}/alliances`);
        if (res.ok) {
          const data = await res.json();
          setAlliances(data);
        }
      } catch (err) {
        console.error("Failed to fetch alliances:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchAlliances();
  }, [apiBase, kdNum]);

  const formatNumber = (n: number) => {
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toLocaleString();
  };

  const sortedAlliances = [...alliances].sort((a, b) => {
    const aVal = a[sortBy as keyof Alliance];
    const bVal = b[sortBy as keyof Alliance];
    if (typeof aVal === "number" && typeof bVal === "number") {
      return sortDir === "asc" ? aVal - bVal : bVal - aVal;
    }
    return 0;
  });

  const handleSort = (field: string) => {
    if (sortBy === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setSortDir("desc");
    }
  };

  const SortIcon = ({ field }: { field: string }) => (
    <span className="ml-1 opacity-50">
      {sortBy === field ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </span>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Alliance Management</h1>
        <p className="text-muted">View and compare alliance statistics</p>
      </div>

      {/* Stats cards */}
      {!loading && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card">
            <p className="text-muted text-sm mb-1">Total Alliances</p>
            <p className="text-2xl font-bold">{alliances.length}</p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Total Members</p>
            <p className="text-2xl font-bold">
              {alliances.reduce((sum, a) => sum + a.member_count, 0)}
            </p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Combined Power</p>
            <p className="text-2xl font-bold">
              {formatNumber(alliances.reduce((sum, a) => sum + a.total_power, 0))}
            </p>
          </div>
          <div className="card">
            <p className="text-muted text-sm mb-1">Combined Kills</p>
            <p className="text-2xl font-bold">
              {formatNumber(alliances.reduce((sum, a) => sum + a.total_kills, 0))}
            </p>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-bg">
                <th className="text-left px-4 py-3 font-medium">Rank</th>
                <th className="text-left px-4 py-3 font-medium">Alliance</th>
                <th 
                  className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("member_count")}
                >
                  Members<SortIcon field="member_count" />
                </th>
                <th 
                  className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("total_power")}
                >
                  Total Power<SortIcon field="total_power" />
                </th>
                <th 
                  className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("avg_power")}
                >
                  Avg Power<SortIcon field="avg_power" />
                </th>
                <th 
                  className="text-right px-4 py-3 font-medium cursor-pointer hover:text-accent"
                  onClick={() => handleSort("total_kills")}
                >
                  Total Kill Points<SortIcon field="total_kills" />
                </th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-muted">
                    <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-accent mx-auto mb-2"></div>
                    Loading...
                  </td>
                </tr>
              ) : sortedAlliances.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-muted">
                    No alliances found
                  </td>
                </tr>
              ) : (
                sortedAlliances.map((alliance, idx) => (
                  <tr key={alliance.alliance} className="border-b border-border hover:bg-border/50">
                    <td className="px-4 py-3 text-muted">{idx + 1}</td>
                    <td className="px-4 py-3">
                      <span className="px-3 py-1 bg-accent/20 text-accent rounded font-medium">
                        {alliance.alliance}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{alliance.member_count}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatNumber(alliance.total_power)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatNumber(alliance.avg_power)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatNumber(alliance.total_kills)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
