import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setCompanyOverride, setToken } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [me, setMe] = useState(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!getToken()) { setMe(null); setReady(true); return null; }
    try { const d = await api.get("/auth/me"); setMe(d); return d; }
    catch { setMe(null); return null; }
    finally { setReady(true); }
  }, []);

  useEffect(() => {
    refresh();
    const out = () => setMe(null);
    window.addEventListener("c2h:logout", out);
    return () => window.removeEventListener("c2h:logout", out);
  }, [refresh]);

  const login = async (email, password) => {
    const d = await api.post("/auth/login", { email, password });
    setToken(d.token); setCompanyOverride(null); setMe(d); return d;
  };
  const signup = async (payload) => {
    const d = await api.post("/auth/signup", payload);
    setToken(d.token); setMe(d); return d;
  };
  const useToken = async (token) => { setToken(token); setCompanyOverride(null); return refresh(); };
  const logout = () => { setToken(null); setCompanyOverride(null); setMe(null); };
  const can = (p) => !!me && (me.user.is_superadmin || (me.permissions || []).includes(p));
  const hasRole = (r) => !!me && (me.roles || []).some((x) => x.role === r);

  return <AuthCtx.Provider value={{ me, ready, login, signup, logout, refresh, can, hasRole, useToken, setMe }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
