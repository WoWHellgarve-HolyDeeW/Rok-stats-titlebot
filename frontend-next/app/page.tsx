"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import Link from "next/link";

export default function LandingPage() {
  const { isAuthenticated, kingdom } = useAuth();
  const router = useRouter();

  useEffect(() => {
    // If already logged in, redirect to kingdom home
    if (isAuthenticated && kingdom) {
      router.push(`/${kingdom}/home`);
    }
  }, [isAuthenticated, kingdom, router]);

  return (
    <div className="min-h-screen relative overflow-hidden">
      {/* Background effects */}
      <div className="absolute inset-0 bg-hero-glow pointer-events-none" />
      <div className="absolute top-1/4 -left-1/4 w-96 h-96 bg-accent/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 -right-1/4 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <header className="relative z-10 border-b border-border/50 backdrop-blur-xl bg-bg/50">
        <div className="container flex items-center justify-between py-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl overflow-hidden">
              <img src="/logo.png" alt="RokHellgarve" className="w-full h-full object-contain" />
            </div>
            <div>
              <span className="text-2xl font-bold tracking-tight">RokHellgarve Stats</span>
              <span className="hidden sm:inline text-text-muted text-sm ml-3">Kingdom Analytics</span>
            </div>
          </div>
          <nav className="flex items-center gap-3">
            <Link href="/login" className="px-5 py-2.5 rounded-xl border border-border/50 hover:border-accent/50 hover:bg-card/50 transition-all duration-200 font-medium text-text-secondary hover:text-text">
              Sign In
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="relative z-10 container py-24 text-center">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-accent/10 border border-accent/30 text-accent text-sm font-medium mb-8">
          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          Rise of Kingdoms Analytics Platform
        </div>
        <h1 className="text-5xl md:text-6xl lg:text-7xl font-bold mb-6 tracking-tight">
          Kingdom Data<br/>
          <span className="gradient-text">Made Simple</span>
        </h1>
        <p className="text-text-secondary text-lg md:text-xl max-w-2xl mx-auto mb-10 leading-relaxed">
          Track kingdom performance, player stats, and battle metrics. Built for competitive play.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link href="/login" className="btn text-lg px-8 py-4 text-center">
            Access Your Kingdom
            <svg className="inline-block w-5 h-5 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="relative z-10 container py-16">
        <div className="text-center mb-12">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">What You Can Do</h2>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 max-w-5xl mx-auto">
          <div className="card p-6">
            <h3 className="font-bold text-lg mb-2">Player Statistics</h3>
            <p className="text-text-muted text-sm">View power, kills, deaths and detailed stats for all kingdom members.</p>
          </div>
          <div className="card p-6">
            <h3 className="font-bold text-lg mb-2">Battle Tracking</h3>
            <p className="text-text-muted text-sm">Track T4/T5 kills, deaths, and kill points with gain calculations.</p>
          </div>
          <div className="card p-6">
            <h3 className="font-bold text-lg mb-2">DKP Formulas</h3>
            <p className="text-text-muted text-sm">Configure custom scoring formulas for your kingdom requirements.</p>
          </div>
          <div className="card p-6">
            <h3 className="font-bold text-lg mb-2">Player Rankings</h3>
            <p className="text-text-muted text-sm">Leaderboards with filtering and search capabilities.</p>
          </div>
          <div className="card p-6">
            <h3 className="font-bold text-lg mb-2">Alliance Management</h3>
            <p className="text-text-muted text-sm">View and compare stats across different alliances.</p>
          </div>
          <div className="card p-6">
            <h3 className="font-bold text-lg mb-2">Inactive Detection</h3>
            <p className="text-text-muted text-sm">Identify inactive players based on power and activity changes.</p>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="relative z-10 container py-16">
        <div className="card bg-gradient-to-r from-accent/10 to-purple-500/10 border-accent/30 text-center py-12 px-8">
          <h2 className="text-3xl font-bold mb-4">Ready to Get Started?</h2>
          <p className="text-text-secondary mb-8 max-w-lg mx-auto">
            Contact your kingdom administrator to get access credentials.
          </p>
          <Link href="/login" className="btn inline-flex items-center gap-2">
            Access Dashboard
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-border/50 py-8">
        <div className="container text-center">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div className="w-8 h-8 rounded-xl overflow-hidden">
              <img src="/logo.png" alt="RokHellgarve" className="w-full h-full object-contain" />
            </div>
            <span className="font-semibold">RokHellgarve Stats</span>
          </div>
          <p className="text-text-muted text-sm">
            © 2026 RokHellgarve Stats. All rights reserved.
          </p>
          <p className="text-text-muted text-xs mt-2">
            This is a fan-made project not affiliated with Lilith Games.
          </p>
        </div>
      </footer>
    </div>
  );
}
