import Link from "next/link";
import { ReactNode } from "react";

export function Shell({ children, kingdom }: { children: ReactNode; kingdom?: string | number }) {
  return (
    <div>
      <header className="border-b border-border bg-[#0d1626]/60 backdrop-blur">
        <div className="container flex items-center justify-between py-4">
          <div>
            <h1 className="text-xl font-bold">RokHellgarve Stats</h1>
            <p className="text-muted text-sm">Kingdom Analytics Dashboard</p>
          </div>
          <nav className="flex gap-3 text-sm text-muted">
            {kingdom && (
              <>
                <Link className="hover:text-text" href={`/kingdoms/${kingdom}`}>Overview</Link>
                <Link className="hover:text-text" href={`/kingdoms/${kingdom}/alliances`}>Alliances</Link>
                <Link className="hover:text-text" href={`/kingdoms/${kingdom}/players`}>Players</Link>
                <Link className="hover:text-text" href={`/kingdoms/${kingdom}/inactive`}>Inactive</Link>
                <Link className="hover:text-text" href={`/kingdoms/${kingdom}/dkp`}>DKP</Link>
              </>
            )}
          </nav>
        </div>
      </header>
      <main className="container py-6 space-y-4">{children}</main>
    </div>
  );
}
