"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";

interface AdminContextType {
  token: string | null;
  username: string | null;
  isSuper: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  isAuthenticated: boolean;
  isLoading: boolean;
}

const AdminContext = createContext<AdminContextType | null>(null);

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

export function AdminProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [isSuper, setIsSuper] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const saved = localStorage.getItem("rok_admin");
    if (saved) {
      try {
        const data = JSON.parse(saved);
        setToken(data.token);
        setUsername(data.username);
        setIsSuper(data.isSuper || false);
      } catch {
        localStorage.removeItem("rok_admin");
      }
    }
    setIsLoading(false);
  }, []);

  const login = async (user: string, pass: string): Promise<boolean> => {
    try {
      console.log("Attempting login to:", `${API_URL}/admin/login`);
      console.log("Payload:", { username: user, password: pass });
      
      const res = await fetch(`${API_URL}/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, password: pass }),
      });
      
      console.log("Response status:", res.status);
      
      if (!res.ok) {
        const errorText = await res.text();
        console.log("Error response:", errorText);
        return false;
      }
      
      const data = await res.json();
      console.log("Login successful:", data);
      setToken(data.access_token);
      setUsername(data.username);
      setIsSuper(data.is_super);
      localStorage.setItem("rok_admin", JSON.stringify({
        token: data.access_token,
        username: data.username,
        isSuper: data.is_super,
      }));
      return true;
    } catch (err) {
      console.error("Login error:", err);
      return false;
    }
  };

  const logout = () => {
    setToken(null);
    setUsername(null);
    setIsSuper(false);
    localStorage.removeItem("rok_admin");
  };

  return (
    <AdminContext.Provider value={{
      token,
      username,
      isSuper,
      login,
      logout,
      isAuthenticated: !!token,
      isLoading,
    }}>
      {children}
    </AdminContext.Provider>
  );
}

export function useAdmin() {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error("useAdmin must be used within AdminProvider");
  return ctx;
}
