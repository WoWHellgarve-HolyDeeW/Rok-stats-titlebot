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
      title: "Live Activity",
      description: "Monitor real-time chat, coordinates, and profile captures",
      href: `/${kingdom}/live`,
      color: "from-purple-500 to-violet-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      ),
    },
    {
      title: "Map",
      description: "View shared coordinates and alliance territories on the map",
      href: `/${kingdom}/map`,
      color: "from-teal-500 to-cyan-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
        </svg>
      ),
    },
    {
      title: "Rankings",
      description: "View power, kill, and merit rankings for the kingdom",
      href: `/${kingdom}/rankings`,
      color: "from-amber-500 to-yellow-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
        </svg>
      ),
    },
    {
      title: "Compare Governors",
      description: "Compare 2-6 governors side by side with charts and stats",
      href: `/${kingdom}/compare`,
      color: "from-indigo-500 to-blue-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
        </svg>
      ),
    },
    {
      title: "KvK Dashboard",
      description: "Track KvK performance, honor, and cross-kingdom battles",
      href: `/${kingdom}/kvk`,
      color: "from-red-500 to-orange-500",
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" />
        </svg>
      ),
    },
    {
      title: "Bot Control",
      description: "Run automated scans to capture player data from the game",
      href: `/${kingdom}/scanner`,
      color: "from-cyan-500 to-sky-500",
      ownerOnly: true,
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      ),
    },
    {
      title: "Bot Logs",
      description: "View history of bot actions, title assignments, and errors",
      href: `/${kingdom}/bot-logs`,
      color: "from-violet-500 to-purple-500",
      ownerOnly: true,
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
        </svg>
      ),
    },
    {
      title: "Schedules",
      description: "Manage automated recurring scans and bot tasks",
      href: `/${kingdom}/schedules`,
      color: "from-lime-500 to-green-500",
      ownerOnly: true,
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
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
