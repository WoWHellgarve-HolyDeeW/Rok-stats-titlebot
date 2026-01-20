"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

interface KingdomStats {
  totalPlayers: number;
  totalAlliances: number;
  totalScans: number;
  lastScan: string | null;
}

interface DashboardCard {
  title: string;
  description: string;
  href: string;
  icon: React.ReactNode;
  color: string;
  stats?: string;
  ownerOnly?: boolean;
}

export default function KingdomHomePage() {
  const params = useParams();
  const kingdom = params.kingdom as string;
  const { accessCode, isOwner } = useAuth();
  const [stats, setStats] = useState<KingdomStats | null>(null);
  const [loading, setLoading] = useState(true);

  const apiBase = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const kdNum = kingdom === "demo" ? 3328 : parseInt(kingdom);
        
        // Fetch summary
        const res = await fetch(`${apiBase}/kingdoms/${kdNum}/summary`);
        if (res.ok) {
          const data = await res.json();
          setStats({
            totalPlayers: data.counts?.governors || 0,
            totalAlliances: data.counts?.alliances || 0,
            totalScans: data.counts?.snapshots || 0,
            lastScan: data.last_scan || null,
          });
        }
      } catch (err) {
        console.error("Failed to fetch stats:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, [kingdom, apiBase]);

  const cards: DashboardCard[] = [
    {
      title: "KD Dashboard",
      description: "View detailed statistics, gains, rankings, and player performance metrics",
      href: `/${kingdom}/kd-dashboard`,
      color: "from-blue-500 to-cyan-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      ),
      stats: stats ? `${stats.totalPlayers.toLocaleString()} players` : undefined,
    },
    {
      title: "Alliance Management",
      description: "View alliance statistics, member counts, and performance comparisons",
      href: `/${kingdom}/alliances`,
      color: "from-green-500 to-emerald-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
        </svg>
      ),
      stats: stats ? `${stats.totalAlliances} alliances` : undefined,
    },
    {
      title: "Player Management",
      description: "Search and view individual player profiles, gains, and history",
      href: `/${kingdom}/players`,
      color: "from-orange-500 to-amber-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      ),
    },
    {
      title: "KvK Seed Analysis",
      description: "View your kingdom's seed classification for KvK matchmaking",
      href: `/${kingdom}/seed`,
      color: "from-pink-500 to-rose-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" />
        </svg>
      ),
    },
    {
      title: "Inactivity Tracker",
      description: "Monitor inactive players and track their last activity dates",
      href: `/${kingdom}/inactive`,
      color: "from-red-500 to-rose-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
    {
      title: "Settings",
      description: "Configure kingdom settings, access codes, and preferences",
      href: `/${kingdom}/settings`,
      color: "from-slate-500 to-gray-500",
      ownerOnly: true,
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
    },
  ];

  // Filter cards based on user role
  const filteredCards = cards.filter(card => !card.ownerOnly || isOwner);

  return (
    <div className="space-y-8">
      {/* Welcome header */}
      <div>
        <h1 className="text-3xl font-bold mb-2">
          Welcome to Kingdom {kingdom}
        </h1>
        <p className="text-text-secondary text-lg">
          Your Rise of Kingdoms analytics dashboard
        </p>
      </div>

      {/* Quick stats */}
      {!loading && stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card relative overflow-hidden group">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-500 to-cyan-500" />
            <p className="text-text-muted text-sm mb-2 uppercase tracking-wider">Total Players</p>
            <p className="text-3xl font-bold text-blue-400">{stats.totalPlayers.toLocaleString()}</p>
          </div>
          <div className="card relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-green-500 to-emerald-500" />
            <p className="text-text-muted text-sm mb-2 uppercase tracking-wider">Alliances</p>
            <p className="text-3xl font-bold text-green-400">{stats.totalAlliances}</p>
          </div>
          <div className="card relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-purple-500 to-pink-500" />
            <p className="text-text-muted text-sm mb-2 uppercase tracking-wider">Total Scans</p>
            <p className="text-3xl font-bold text-purple-400">{stats.totalScans}</p>
          </div>
          <div className="card relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-orange-500 to-amber-500" />
            <p className="text-text-muted text-sm mb-2 uppercase tracking-wider">Last Scan</p>
            <p className="text-xl font-bold text-orange-400">
              {stats.lastScan 
                ? new Date(stats.lastScan).toLocaleDateString()
                : "No scans"
              }
            </p>
          </div>
        </div>
      )}

      {/* Dashboard cards */}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredCards.map((card) => (
          <Link key={card.href} href={card.href} className="group">
            <div className="card h-full hover:border-accent/40 transition-all duration-300 group-hover:shadow-card-hover group-hover:-translate-y-1">
              <div className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${card.color} flex items-center justify-center mb-5 text-white shadow-lg group-hover:scale-110 transition-transform duration-300`}>
                {card.icon}
              </div>
              <h3 className="text-xl font-bold mb-2 group-hover:text-accent transition-colors">
                {card.title}
              </h3>
              <p className="text-text-muted text-sm mb-4 leading-relaxed">
                {card.description}
              </p>
              {card.stats && (
                <div className="inline-flex items-center gap-2 text-xs font-semibold text-accent bg-accent/10 px-3 py-1.5 rounded-lg">
                  <div className="w-1.5 h-1.5 rounded-full bg-accent" />
                  {card.stats}
                </div>
              )}
            </div>
          </Link>
        ))}
      </div>

      {/* Share link info (only show to owners) */}
      {kingdom !== "demo" && accessCode && isOwner && (
        <div className="card bg-gradient-to-r from-accent/5 to-purple-500/5 border-accent/30">
          <div className="flex items-start gap-5">
            <div className="w-12 h-12 rounded-xl bg-accent/15 flex items-center justify-center flex-shrink-0 border border-accent/30">
              <svg className="w-6 h-6 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
              </svg>
            </div>
            <div>
              <h4 className="font-bold text-lg mb-2">Share with Alliance</h4>
              <p className="text-text-muted text-sm mb-4 leading-relaxed">
                Go to Settings to get the share link for your alliance members.
              </p>
              <a href={`/${kingdom}/settings`} className="btn inline-flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Go to Settings
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
