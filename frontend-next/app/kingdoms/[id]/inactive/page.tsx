"use client";
import { use } from "react";
import useSWR from "swr";
import { Shell } from "@/components/layout";
import { SimpleTable } from "@/components/table";
import { fmt } from "@/components/format";
import { fetchJson } from "@/components/api";

export default function InactivePage({ params }: { params: Promise<{ id: string }> }) {
  const { id: k } = use(params);
  const { data } = useSWR(() => `/kingdoms/${k}/inactive`, fetchJson);
  const rows = Array.isArray(data) ? data : [];

  return (
    <Shell kingdom={k}>
      <div className="card space-y-3">
        <div className="text-sm text-muted">Kingdom {k}</div>
        <h2 className="text-xl font-semibold">Inactive (janela completa de scans)</h2>
        {data ? (
          <SimpleTable
            rows={rows}
            columns={[
              { label: "Gov", key: "governor_name" },
              { label: "Alliance", key: "alliance_name" },
              { label: "Last Scan", key: "last_scan" },
              { label: "Power Δ", key: "power_gain", align: "right", render: (r: any) => fmt(r.power_gain) },
              { label: "KP Δ", key: "kp_gain", align: "right", render: (r: any) => fmt(r.kp_gain) },
              { label: "Status", key: "status" },
            ]}
          />
        ) : (
          <div className="text-muted">Carregando…</div>
        )}
      </div>
    </Shell>
  );
}
