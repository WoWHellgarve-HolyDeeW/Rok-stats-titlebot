"use client";
import React, { use } from "react";
import useSWR from "swr";
import { Shell } from "@/components/layout";
import { SimpleTable } from "@/components/table";
import { fmt } from "@/components/format";
import { fetchJson } from "@/components/api";

export default function DKPPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: k } = use(params);
  const { data } = useSWR(() => `/kingdoms/${k}/dkp?limit=200`, fetchJson);
  const rows = Array.isArray(data) ? data : [];

  return (
    <Shell kingdom={k}>
      <div className="card space-y-3">
        <div className="text-sm text-muted">Kingdom {k}</div>
        <h2 className="text-xl font-semibold">DKP Ranking</h2>
        <p className="text-muted text-sm">
          DKP = (ΔT4 × peso_t4) + (ΔT5 × peso_t5) + (ΔDead × peso_dead)
        </p>
        {rows.length > 0 ? (
          <SimpleTable
            rows={rows}
            columns={[
              { label: "Gov", key: "governor_name" },
              { label: "Alliance", key: "alliance_name" },
              { label: "ΔT4", key: "delta_t4", align: "right", render: (r: any) => fmt(r.delta_t4) },
              { label: "ΔT5", key: "delta_t5", align: "right", render: (r: any) => fmt(r.delta_t5) },
              { label: "ΔDead", key: "delta_dead", align: "right", render: (r: any) => fmt(r.delta_dead) },
              { label: "DKP", key: "dkp", align: "right", render: (r: any) => fmt(r.dkp) },
            ]}
          />
        ) : (
          <div className="text-muted">Carregando…</div>
        )}
      </div>
    </Shell>
  );
}
