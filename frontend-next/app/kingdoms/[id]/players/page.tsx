"use client";
import { useState, use } from "react";
import useSWR from "swr";
import { Shell } from "@/components/layout";
import { SimpleTable } from "@/components/table";
import { fmt } from "@/components/format";
import { fetchJson } from "@/components/api";

export default function PlayersPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: k } = use(params);
  const [alliance, setAlliance] = useState("");
  const [powerMin, setPowerMin] = useState("");
  const [powerMax, setPowerMax] = useState("");
  const [kpMin, setKpMin] = useState("");
  const [kpMax, setKpMax] = useState("");

  const query = `/kingdoms/${k}/top-power?limit=200&page=1${
    alliance ? `&alliance=${encodeURIComponent(alliance)}` : ""
  }${powerMin ? `&power_min=${powerMin}` : ""}${powerMax ? `&power_max=${powerMax}` : ""}${
    kpMin ? `&kp_min=${kpMin}` : ""
  }${kpMax ? `&kp_max=${kpMax}` : ""}`;

  const { data } = useSWR(query, fetchJson);
  const rows = Array.isArray(data) ? data : [];

  return (
    <Shell kingdom={k}>
      <div className="card space-y-3">
        <div className="flex flex-col gap-2">
          <div className="text-sm text-muted">Kingdom {k}</div>
          <h2 className="text-xl font-semibold">Players</h2>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-2 text-sm">
            <input className="bg-[#0d1626] border border-border rounded px-2 py-1" placeholder="Alliance" value={alliance} onChange={(e) => setAlliance(e.target.value)} />
            <input className="bg-[#0d1626] border border-border rounded px-2 py-1" placeholder="Power min" value={powerMin} onChange={(e) => setPowerMin(e.target.value)} />
            <input className="bg-[#0d1626] border border-border rounded px-2 py-1" placeholder="Power max" value={powerMax} onChange={(e) => setPowerMax(e.target.value)} />
            <input className="bg-[#0d1626] border border-border rounded px-2 py-1" placeholder="KP min" value={kpMin} onChange={(e) => setKpMin(e.target.value)} />
            <input className="bg-[#0d1626] border border-border rounded px-2 py-1" placeholder="KP max" value={kpMax} onChange={(e) => setKpMax(e.target.value)} />
          </div>
        </div>

        {rows.length > 0 ? (
          <SimpleTable
            rows={rows}
            columns={[
              { label: "Gov", key: "name" },
              { label: "Alliance", key: "alliance" },
              { label: "Power", key: "power", align: "right", render: (r: any) => fmt(r.power) },
              { label: "KP", key: "kill_points", align: "right", render: (r: any) => fmt(r.kill_points) },
            ]}
          />
        ) : (
          <div className="text-muted">Carregando…</div>
        )}
      </div>
    </Shell>
  );
}
