"use client";
import { ReactNode, useEffect, useState } from "react";
import { useParams, useRouter, usePathname, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Link from "next/link";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
  ownerOnly?: boolean;
}

interface NavSection {
  title: string;
  ownerOnly?: boolean;
  items: NavItem[];
}

export default function KingdomLayout({ children }: { children: ReactNode }) {
  const params = useParams();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isAuthenticated, kingdom, logout, isLoading, loginWithCode, isOwner } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [codeLoginAttempted, setCodeLoginAttempted] = useState(false);

  const kingdomParam = params.kingdom as string;
  const isDemo = kingdomParam === "demo";
  const urlCode = searchParams.get("code");

  // Try to login with access code from URL
  useEffect(() => {
    if (urlCode && !isAuthenticated && !isLoading && !codeLoginAttempted) {
      setCodeLoginAttempted(true);
      loginWithCode(urlCode).then((success) => {
        if (success) {
          // Remove code from URL after successful login
          const newUrl = pathname;
          router.replace(newUrl);
        }
      });
    }
  }, [urlCode, isAuthenticated, isLoading, codeLoginAttempted, loginWithCode, pathname, router]);

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isDemo && !urlCode) {
      router.push("/login");
    }
  }, [isAuthenticated, isLoading, isDemo, router, urlCode]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-accent"></div>
      </div>
    );
  }

  if (!isAuthenticated && !isDemo) {
    return null;
  }

  const navSections: NavSection[] = [
    {
      title: "Overview",
      items: [
        {
          href: `/${kingdomParam}/home`,
          label: "Home",
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
          ),
        },
        {
          href: `/${kingdomParam}/kd-dashboard`,
          label: "KD Dashboard",
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          ),
        },
      ],
    },
    {
      title: "Data",
      items: [
        {
          href: `/${kingdomParam}/compare`,
          label: "Compare",
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
          ),
        },
      ],
    },
    {
      title: "Analysis",
      items: [
        {
          href: `/${kingdomParam}/trends`,
          label: "Trends",
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          ),
        },
        {
          href: `/${kingdomParam}/kvk`,
          label: "KvK",
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          ),
        },
        {
          href: `/${kingdomParam}/analytics`,
          label: "Combat Analytics",
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          ),
        },
        {
          href: `/${kingdomParam}/inactive`,
          label: "Inactive",
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          ),
        },
      ],
    },
    {
      title: "Bot",
      ownerOnly: true,
      items: [
        {
          href: `/${kingdomParam}/scanner`,
          label: "Bot Control",
          ownerOnly: true,
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          ),
        },
        {
          href: `/${kingdomParam}/bot-logs`,
          label: "Bot Logs",
          ownerOnly: true,
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
            </svg>
          ),
        },
        {
          href: `/${kingdomParam}/schedules`,
          label: "Schedules",
          ownerOnly: true,
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          ),
        },
      ],
    },
    {
      title: "",
      ownerOnly: true,
      items: [
        {
          href: `/${kingdomParam}/map`,
          label: "Kingdom Map",
          ownerOnly: true,
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
          ),
        },
        {
          href: `/${kingdomParam}/settings`,
          label: "Settings",
          ownerOnly: true,
          icon: (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          ),
        },
      ],
    },
  ];

  // Filter sections based on user role
  const filteredSections = navSections
    .filter(section => !section.ownerOnly || isOwner)
    .map(section => ({
      ...section,
      items: section.items.filter(item => !item.ownerOnly || isOwner),
    }))
    .filter(section => section.items.length > 0);

  const isActive = (href: string) => pathname === href;

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-72 bg-gradient-to-b from-card to-bg-secondary border-r border-border/50 transform transition-transform duration-300 ease-out lg:translate-x-0 lg:static ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center gap-4 px-6 py-6 border-b border-border/50">
            <div className="w-12 h-12 rounded-2xl overflow-hidden">
              <img src="/logo.png" alt="RokHellgarve" className="w-full h-full object-contain" />
            </div>
            <div>
              <h1 className="font-bold text-xl tracking-tight">RokHellgarve</h1>
              <p className="text-sm text-text-muted font-medium">Kingdom {kingdomParam}</p>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto">
            {filteredSections.map((section, sIdx) => (
              <div key={section.title || sIdx}>
                {sIdx > 0 && <div className="my-3 border-t border-border/30" />}
                {section.title && (
                  <p className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted/60">
                    {section.title}
                  </p>
                )}
                <div className="space-y-0.5">
                  {section.items.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-3 px-4 py-2.5 rounded-xl transition-all duration-200 ${
                        isActive(item.href)
                          ? "bg-accent/15 text-accent border border-accent/30 shadow-sm"
                          : "text-text-secondary hover:bg-card-hover hover:text-text border border-transparent"
                      }`}
                      onClick={() => setSidebarOpen(false)}
                    >
                      <span className={isActive(item.href) ? "text-accent" : "text-text-muted"}>
                        {item.icon}
                      </span>
                      <span className="font-medium text-sm">{item.label}</span>
                      {isActive(item.href) && (
                        <div className="ml-auto w-1.5 h-1.5 rounded-full bg-accent shadow-glow-blue" />
                      )}
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          {/* User section */}
          <div className="border-t border-border/50 p-4">
            {!isDemo && isOwner && (
              <Link
                href={`/${kingdomParam}/settings`}
                className="flex items-center gap-3 mb-4 px-4 py-3.5 bg-bg-secondary/50 rounded-xl border border-border/30 hover:border-accent/30 transition-colors"
                onClick={() => setSidebarOpen(false)}
              >
                <svg className="w-5 h-5 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                </svg>
                <span className="text-sm font-medium text-text-muted">Share Dashboard</span>
              </Link>
            )}
            <button
              onClick={handleLogout}
              className="flex items-center gap-3 w-full px-4 py-3.5 rounded-xl text-text-muted hover:bg-danger/10 hover:text-danger transition-all duration-200 border border-transparent hover:border-danger/30"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
              <span className="font-medium">Logout</span>
            </button>
          </div>
        </div>
      </aside>

      {/* Overlay for mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="sticky top-0 z-30 h-16 bg-bg/80 backdrop-blur-xl border-b border-border/50 flex items-center px-4 lg:px-8">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden p-2.5 rounded-xl hover:bg-card-hover transition-colors"
          >
            <svg className="w-6 h-6 text-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          
          <div className="flex-1" />
          
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2 px-4 py-2 rounded-xl bg-card/50 border border-border/50">
              <div className="w-2 h-2 rounded-full bg-success animate-pulse" />
              <span className="text-text-secondary text-sm font-medium">
                KD {kingdomParam}
              </span>
            </div>
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent to-purple-600 flex items-center justify-center text-white font-bold text-sm shadow-glow-blue">
              {kingdomParam.slice(-2)}
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 p-4 lg:p-8 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
