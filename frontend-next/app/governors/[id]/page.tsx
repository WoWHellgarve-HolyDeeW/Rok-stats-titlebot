"use client";
import React, { use } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetchJson } from "@/components/api";
import { fmt } from "@/components/format";

export default function GovernorDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: govId } = use(params);
  const { data, error } = useSWR(() => `/governors/${govId}`, fetchJson);

  if (error) {
    return (
      <main className="container py-8">
        <div className="card">
          <h1 className="text-xl font-bold text-red-400">Erro</h1>
          <p className="text-muted">Governador não encontrado ou falha de conexão.</p>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="container py-8">
        <div className="card text-muted">Carregando…</div>
      </main>
    );
  }

  const gov = data as any;

  return (
    <main className="container py-8 space-y-6">
      <header className="border-b border-border pb-4">
        <h1 className="text-2xl font-bold">{gov.name}</h1>
        <p className="text-muted text-sm">
          ID: {gov.governor_id} · Kingdom:{" "}
          <Link href={`/kingdoms/${gov.kingdom}`} className="underline">
            {gov.kingdom}
          </Link>{" "}
          · Alliance: {gov.alliance ?? "N/A"}
        </p>
      </header>

      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card">
          <div className="text-muted text-sm">Power</div>
          <div className="text-2xl font-semibold">{fmt(gov.latest?.power)}</div>
          {gov.deltas?.power !== null && (
            <div className={`text-sm ${gov.deltas.power >= 0 ? "text-green-400" : "text-red-400"}`}>
              {gov.deltas.power >= 0 ? "+" : ""}
              {fmt(gov.deltas.power)}
            </div>
          )}
        </div>
        <div className="card">
          <div className="text-muted text-sm">Kill Points</div>
          <div className="text-2xl font-semibold">{fmt(gov.latest?.kill_points)}</div>
          {gov.deltas?.kill_points !== null && (
            <div className={`text-sm ${gov.deltas.kill_points >= 0 ? "text-green-400" : "text-red-400"}`}>
              {gov.deltas.kill_points >= 0 ? "+" : ""}
              {fmt(gov.deltas.kill_points)}
            </div>
          )}
        </div>
        <div className="card">
          <div className="text-muted text-sm">Dead</div>
          <div className="text-2xl font-semibold">{fmt(gov.latest?.dead)}</div>
          {gov.deltas?.dead !== null && (
            <div className={`text-sm ${gov.deltas.dead >= 0 ? "text-green-400" : "text-red-400"}`}>
              {gov.deltas.dead >= 0 ? "+" : ""}
              {fmt(gov.deltas.dead)}
            </div>
          )}
        </div>
      </section>

      <section className="card space-y-3">
        <h2 className="text-lg font-semibold">Último Snapshot</h2>
        {gov.latest ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted">T4 Kills:</span> {fmt(gov.latest.t4_kills)}
            </div>
            <div>
              <span className="text-muted">T5 Kills:</span> {fmt(gov.latest.t5_kills)}
            </div>
            <div>
              <span className="text-muted">RSS Gathered:</span> {fmt(gov.latest.rss_gathered)}
            </div>
            <div>
              <span className="text-muted">RSS Assistance:</span> {fmt(gov.latest.rss_assistance)}
            </div>
            <div>
              <span className="text-muted">Helps:</span> {fmt(gov.latest.helps)}
            </div>
            <div>
              <span className="text-muted">Scan:</span> {gov.latest.created_at}
            </div>
          </div>
        ) : (
          <p className="text-muted">Sem dados.</p>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="text-lg font-semibold">Histórico ({gov.history?.length ?? 0} snapshots)</h2>
        {gov.history && gov.history.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm table">
              <thead>
                <tr className="text-muted">
                  <th className="text-left">Data</th>
                  <th className="text-right">Power</th>
                  <th className="text-right">KP</th>
                  <th className="text-right">Dead</th>
                  <th className="text-right">T4</th>
                  <th className="text-right">T5</th>
                </tr>
              </thead>
              <tbody>
                {gov.history.map((s: any, i: number) => (
                  <tr key={i} className="hover:bg-[#0d1626]">
                    <td>{s.created_at}</td>
                    <td className="text-right">{fmt(s.power)}</td>
                    <td className="text-right">{fmt(s.kill_points)}</td>
                    <td className="text-right">{fmt(s.dead)}</td>
                    <td className="text-right">{fmt(s.t4_kills)}</td>
                    <td className="text-right">{fmt(s.t5_kills)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-muted">Sem histórico disponível.</p>
        )}
      </section>
    </main>
  );
}
