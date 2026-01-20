"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";

interface AuthContextType {
  token: string | null;
  kingdom: number | null;
  accessCode: string | null;
  isOwner: boolean;
  login: (kingdom: number, password: string) => Promise<boolean>;
  loginWithCode: (code: string) => Promise<boolean>;
  logout: () => void;
  isAuthenticated: boolean;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [kingdom, setKingdom] = useState<number | null>(null);
  const [accessCode, setAccessCode] = useState<string | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Load from localStorage on mount
    const saved = localStorage.getItem("rok_auth");
    if (saved) {
      try {
        const data = JSON.parse(saved);
        setToken(data.token);
        setKingdom(data.kingdom);
        setAccessCode(data.accessCode || null);
        setIsOwner(data.isOwner || false);
      } catch {
        localStorage.removeItem("rok_auth");
      }
    }
    setIsLoading(false);
  }, []);

  const login = async (kingdomNum: number, password: string): Promise<boolean> => {
    try {
      console.log("[auth] login ->", kingdomNum, `${API_URL}/auth/login`);
      const res = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kingdom: kingdomNum, password }),
      });
      
      console.log("[auth] status", res.status);
      if (!res.ok) {
        try {
          const txt = await res.text();
          console.error("[auth] error", res.status, txt);
        } catch (e) {
          console.error("[auth] error", res.status, e);
        }
        return false;
      }
      
      const data = await res.json();
      setToken(data.access_token);
      setKingdom(data.kingdom);
      setAccessCode(data.access_code || null);
      setIsOwner(true);
      localStorage.setItem("rok_auth", JSON.stringify({
        token: data.access_token,
        kingdom: data.kingdom,
        accessCode: data.access_code,
        isOwner: true,
      }));
      return true;
    } catch {
      return false;
    }
  };

  const loginWithCode = async (code: string): Promise<boolean> => {
    try {
      console.log("[auth] loginWithCode ->", code);
      const res = await fetch(`${API_URL}/auth/access-code?code=${encodeURIComponent(code)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      
      if (!res.ok) {
        console.error("[auth] code login failed", res.status);
        return false;
      }
      
      const data = await res.json();
      setToken(data.access_token);
      setKingdom(data.kingdom);
      setAccessCode(data.access_code || null);
      setIsOwner(false);
      localStorage.setItem("rok_auth", JSON.stringify({
        token: data.access_token,
        kingdom: data.kingdom,
        accessCode: data.access_code,
        isOwner: false,
      }));
      return true;
    } catch {
      return false;
    }
  };

  const logout = () => {
    setToken(null);
    setKingdom(null);
    setAccessCode(null);
    setIsOwner(false);
    localStorage.removeItem("rok_auth");
  };

  return (
    <AuthContext.Provider value={{
      token,
      kingdom,
      accessCode,
      isOwner,
      login,
      loginWithCode,
      logout,
      isAuthenticated: !!token,
      isLoading,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

// Fetch helper with auth
export async function fetchWithAuth<T>(path: string, token: string | null): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  
  const res = await fetch(`${API_URL}${path}`, { headers });
  if (!res.ok) {
    throw new Error(`Error ${res.status}: ${res.statusText}`);
  }
  return res.json();
}
