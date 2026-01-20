import { ReactNode } from "react";
import { AdminProvider } from "@/lib/admin";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AdminProvider>
      {children}
    </AdminProvider>
  );
}
