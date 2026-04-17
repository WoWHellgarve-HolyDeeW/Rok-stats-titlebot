import { ReactNode } from "react";
import clsx from "clsx";

export type Column<T> = {
  key: keyof T | string;
  label: string;
  align?: "left" | "right";
  render?: (row: T, index: number) => ReactNode;
};

export function SimpleTable<T>({ rows, columns }: { rows: T[]; columns: Column<T>[] }) {
  return (
    <table className="w-full text-sm table">
      <thead>
        <tr className="text-muted">
          {columns.map((c) => (
            <th key={String(c.key)} className={clsx("text-left", c.align === "right" && "text-right")}>{c.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="hover:bg-[#0d1626]">
            {columns.map((c) => (
              <td key={String(c.key)} className={clsx(c.align === "right" && "text-right")}> {c.render ? c.render(r, i) : (r as any)[c.key]}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
