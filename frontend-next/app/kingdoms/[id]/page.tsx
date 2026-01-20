"use client";
import React, { use } from "react";
import useSWR from "swr";
import { Shell } from "@/components/layout";
import { SimpleTable } from "@/components/table";
import { fmt } from "@/components/format";
import { fetchJson } from "@/components/api";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card space-y-3">
      <div className="text-sm text-muted uppercase tracking-wide">{title}</div>
      {children}
    </div>
  );
}

export default function KingdomPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: k } = use(params);
  const { data: summaryData } = useSWR(() => `/kingdoms/${k}/summary`, fetchJson);
  const { data: topPowerData } = useSWR(() => `/kingdoms/${k}/top-power?limit=20`, fetchJson);
  const { data: topKPData } = useSWR(() => `/kingdoms/${k}/top-killpoints?limit=20`, fetchJson);
  const { data: gainPowerData } = useSWR(() => `/kingdoms/${k}/top-power-gain?limit=20`, fetchJson);
  const { data: gainKPData } = useSWR(() => `/kingdoms/${k}/top-kp-gain?limit=20`, fetchJson);
  const { data: dkpData } = useSWR(() => `/kingdoms/${k}/dkp?limit=20`, fetchJson);
  const { data: inactiveData } = useSWR(() => `/kingdoms/${k}/inactive`, fetchJson);
  const { data: alliancesData } = useSWR(() => `/kingdoms/${k}/alliances/top-power?limit=20`, fetchJson);

  // Type assertions for safe usage
  const summary = summaryData as { counts?: { kingdoms?: number; alliances?: number; governors?: number; snapshots?: number } } | undefined;
  const topPower = Array.isArray(topPowerData) ? topPowerData : [];
  const topKP = Array.isArray(topKPData) ? topKPData : [];
  const gainPower = Array.isArray(gainPowerData) ? gainPowerData : [];
  const gainKP = Array.isArray(gainKPData) ? gainKPData : [];
  const dkp = Array.isArray(dkpData) ? dkpData : [];
  const inactive = Array.isArray(inactiveData) ? inactiveData : [];
  const alliances = Array.isArray(alliancesData) ? alliancesData : [];

  return (
    <Shell kingdom={k}>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <Card title="Resumo">
          {summary ? (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="card" style={{ padding: 8 }}>Reinos<br/><strong>{summary.counts?.kingdoms ?? 0}</strong></div>
              <div className="card" style={{ padding: 8 }}>Alianças<br/><strong>{summary.counts?.alliances ?? 0}</strong></div>
              <div className="card" style={{ padding: 8 }}>Governadores<br/><strong>{summary.counts?.governors ?? 0}</strong></div>
              <div className="card" style={{ padding: 8 }}>Snapshots<br/><strong>{summary.counts?.snapshots ?? 0}</strong></div>
            </div>
          ) : (
            <div className="text-muted">Carregando…</div>
          )}
        </Card>

        <Card title="Top Power">
          {topPower.length > 0 ? (
            <SimpleTable
              rows={topPower}
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
        </Card>

        <Card title="Top KP">
          {topKP.length > 0 ? (
            <SimpleTable
              rows={topKP}
              columns={[
                { label: "Gov", key: "name" },
                { label: "Alliance", key: "alliance" },
                { label: "KP", key: "kill_points", align: "right", render: (r: any) => fmt(r.kill_points) },
                { label: "Power", key: "power", align: "right", render: (r: any) => fmt(r.power) },
              ]}
            />
          ) : (
            <div className="text-muted">Carregando…</div>
          )}
        </Card>

        <Card title="Power Gain">
          {gainPower.length > 0 ? (
            <SimpleTable
              rows={gainPower}
              columns={[
                { label: "Gov", key: "governor_name" },
                { label: "Alliance", key: "alliance_name" },
                { label: "Power Δ", key: "power_gain", align: "right", render: (r: any) => fmt(r.power_gain) },
                { label: "KP Δ", key: "kp_gain", align: "right", render: (r: any) => fmt(r.kp_gain) },
              ]}
            />
          ) : (
            <div className="text-muted">Carregando…</div>
          )}
        </Card>

        <Card title="KP Gain">
          {gainKP.length > 0 ? (
            <SimpleTable
              rows={gainKP}
              columns={[
                { label: "Gov", key: "governor_name" },
                { label: "Alliance", key: "alliance_name" },
                { label: "KP Δ", key: "kp_gain", align: "right", render: (r: any) => fmt(r.kp_gain) },
                { label: "Power Δ", key: "power_gain", align: "right", render: (r: any) => fmt(r.power_gain) },
              ]}
            />
          ) : (
            <div className="text-muted">Carregando…</div>
          )}
        </Card>

        <Card title="DKP">
          {dkp.length > 0 ? (
            <SimpleTable
              rows={dkp}
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
        </Card>

        <Card title="Alliances">
          {alliances.length > 0 ? (
            <SimpleTable
              rows={alliances}
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
        </Card>

        <Card title="Inativos (janela de scans)">
          {inactive.length > 0 ? (
            <SimpleTable
              rows={inactive}
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
        </Card>
      </div>
    </Shell>
  );
}
