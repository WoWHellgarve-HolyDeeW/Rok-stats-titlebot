"use client";
import { use } from "react";
import useSWR from "swr";
import { Shell } from "@/components/layout";
import { SimpleTable } from "@/components/table";
import { fmt } from "@/components/format";
import { fetchJson } from "@/components/api";

export default function AlliancesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: k } = use(params);
  const { data } = useSWR(() => `/kingdoms/${k}/alliances/top-power?limit=200`, fetchJson);
  const rows = Array.isArray(data) ? data : [];

  return (
    <Shell kingdom={k}>
      <div className="card space-y-3">
        <div className="flex justify-between items-center">
          <div>
            <div className="text-sm text-muted">Kingdom {k}</div>
            <h2 className="text-xl font-semibold">Alliances</h2>
          </div>
        </div>
        {data ? (
          <SimpleTable
            rows={rows}
            columns={[
              { label: "Alliance", key: "alliance" },
              { label: "Members", key: "members", align: "right" },
              { label: "Power", key: "total_power", align: "right", render: (r: any) => fmt(r.total_power) },
              { label: "KP", key: "total_kp", align: "right", render: (r: any) => fmt(r.total_kp) },
            ]}
          />
        ) : (
          <div className="text-muted">Carregando…</div>
        )}
      </div>
    </Shell>
  );
}
