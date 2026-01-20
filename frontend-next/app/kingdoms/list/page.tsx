"use client";
import React from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetchJson } from "@/components/api";
import { fmt } from "@/components/format";

export default function KingdomsListPage() {
  const { data } = useSWR("/kingdoms", fetchJson);

  return (
    <main className="container py-8 space-y-6">
      <header className="border-b border-border pb-4">
        <h1 className="text-2xl font-bold">RokHellgarve Stats</h1>
        <p className="text-muted text-sm">Selecione um reino para ver o dashboard completo.</p>
      </header>

      <section className="card">
        <h2 className="text-lg font-semibold mb-3">Kingdoms com dados</h2>
        {data ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm table">
              <thead>
                <tr className="text-muted">
                  <th className="text-left">Kingdom</th>
                  <th className="text-right">Governors</th>
                  <th className="text-right">Alliances</th>
                  <th className="text-right">Snapshots</th>
                  <th className="text-left">Primeiro Scan</th>
                  <th className="text-left">Último Scan</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(data as any[]).map((k: any) => (
                  <tr key={k.number} className="hover:bg-[#0d1626]">
                    <td className="font-semibold">{k.number}</td>
                    <td className="text-right">{fmt(k.governors)}</td>
                    <td className="text-right">{fmt(k.alliances)}</td>
                    <td className="text-right">{fmt(k.snapshots)}</td>
                    <td>{k.first_scan ?? "-"}</td>
                    <td>{k.last_scan ?? "-"}</td>
                    <td>
                      <Link
                        href={`/kingdoms/${k.number}`}
                        className="text-blue-400 underline hover:text-blue-300"
                      >
                        Abrir
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-muted">Carregando…</div>
        )}
      </section>

      <section className="card">
        <h2 className="text-lg font-semibold mb-2">Ou digite manualmente</h2>
        <form className="flex flex-col sm:flex-row gap-3" action="/kingdoms">
          <input
            name="k"
            type="number"
            placeholder="Número do reino (ex: 3328)"
            className="bg-[#0d1626] border border-border rounded-md px-3 py-2 text-sm flex-1"
            required
          />
          <button className="btn" type="submit">Abrir dashboard</button>
        </form>
      </section>
    </main>
  );
}
