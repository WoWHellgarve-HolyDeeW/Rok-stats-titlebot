"use client";
import { createContext, useContext, useState, useEffect, ReactNode } from "react";

interface AuthContextType {
  token: string | null;
  kingdom: number | null;
  accessCode: string | null;
  isOwner: boolean;
  login: (kingdom: number, password: string) => Promise<{ success: boolean; error?: string }>;
  loginWithCode: (code: string) => Promise<boolean>;
  logout: () => void;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthResponsePayload {
  access_token: string;
  kingdom: number;
  access_code?: string | null;
  is_owner: boolean;
}

interface AuthStatusPayload {
  kingdom: number;
  is_owner: boolean;
}

interface StoredAuthPayload {
  token: string;
  kingdom: number;
  accessCode: string | null;
  isOwner: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api").trim();

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [kingdom, setKingdom] = useState<number | null>(null);
  const [accessCode, setAccessCode] = useState<string | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const applySession = (session: StoredAuthPayload) => {
    setToken(session.token);
    setKingdom(session.kingdom);
    setAccessCode(session.accessCode);
    setIsOwner(session.isOwner);
    localStorage.setItem("rok_auth", JSON.stringify(session));
  };

  const clearSession = () => {
    setToken(null);
    setKingdom(null);
    setAccessCode(null);
    setIsOwner(false);
    localStorage.removeItem("rok_auth");
  };

  useEffect(() => {
    let cancelled = false;

    const hydrateAuth = async () => {
      const saved = localStorage.getItem("rok_auth");
      if (!saved) {
        if (!cancelled) {
          setIsLoading(false);
        }
        return;
      }

      try {
        const data = JSON.parse(saved);
        if (!data?.token || typeof data.kingdom !== "number") {
          throw new Error("Invalid stored auth session");
        }

        const savedSession: StoredAuthPayload = {
          token: data.token,
          kingdom: data.kingdom,
          accessCode: data.accessCode || null,
          isOwner: !!data.isOwner,
        };

        if (cancelled) {
          return;
        }

        setToken(savedSession.token);
        setKingdom(savedSession.kingdom);
        setAccessCode(savedSession.accessCode);
        setIsOwner(savedSession.isOwner);

        try {
          const res = await fetch(`${API_URL}/auth/me`, {
            headers: { Authorization: `Bearer ${savedSession.token}` },
          });

          if (cancelled) {
            return;
          }

          if (res.status === 401 || res.status === 403) {
            clearSession();
            return;
          }

          if (res.ok) {
            const profile = (await res.json()) as AuthStatusPayload;
            applySession({
              token: savedSession.token,
              kingdom: profile.kingdom,
              accessCode: savedSession.accessCode,
              isOwner: !!profile.is_owner,
            });
          }
        } catch {
          // Keep the cached session if the backend is temporarily unreachable.
        }
      } catch {
        if (!cancelled) {
          clearSession();
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void hydrateAuth();

    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (
    kingdomNum: number,
    password: string,
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kingdom: kingdomNum, password }),
      });
      
      if (!res.ok) {
        try {
          const payload = await res.json();
          return { success: false, error: payload?.detail || "Login failed" };
        } catch {
          return { success: false, error: "Login failed" };
        }
      }
      
      const data = (await res.json()) as AuthResponsePayload;
      applySession({
        token: data.access_token,
        kingdom: data.kingdom,
        accessCode: data.access_code || null,
        isOwner: !!data.is_owner,
      });
      return { success: true };
    } catch {
      return { success: false, error: "Unable to reach the server" };
    }
  };

  const loginWithCode = async (code: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API_URL}/auth/access-code?code=${encodeURIComponent(code)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      
      if (!res.ok) {
        return false;
      }
      
      const data = (await res.json()) as AuthResponsePayload;
      applySession({
        token: data.access_token,
        kingdom: data.kingdom,
        accessCode: data.access_code || null,
        isOwner: !!data.is_owner,
      });
      return true;
    } catch {
      return false;
    }
  };

  const logout = () => {
    clearSession();
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
