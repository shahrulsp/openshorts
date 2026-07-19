// Auth/session state for both hosted cloud mode and the new independent SaaS mode.
// - Reads /api/config to learn which auth model is active.
// - Hosted cloud keeps magic-link / Google OAuth behavior.
// - Independent SaaS uses direct email/password auth via /api/saas/*
// - Self-host BYOK remains inert when no managed auth mode is enabled.
import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getApiUrl } from '../config';
import { apiFetch, apiJson, getToken, setToken, clearToken } from '../lib/api';

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [config, setConfig] = useState({
    billingEnabled: false,
    googleAuthEnabled: false,
    saasEnabled: false,
    geminiConfigured: false,
    uploadPostConfigured: false,
  });
  const [me, setMe] = useState(null);           // /api/me payload, or null when signed out
  const [loading, setLoading] = useState(true);
  const [signingIn, setSigningIn] = useState(false);

  const refreshMe = useCallback(async (configOverride = null) => {
    const effectiveConfig = configOverride || config;
    if (!getToken()) { setMe(null); return null; }
    try {
      const sessionPath = effectiveConfig.saasEnabled ? '/api/saas/me' : '/api/me';
      const data = await apiJson(sessionPath);
      setMe(data);
      return data;
    } catch (e) {
      // Stale/invalid token: drop it and fall back to anonymous BYOK.
      clearToken();
      setMe(null);
      return null;
    }
  }, [config]);

  // Handle auth redirect hashes: #/auth/verify?ml=... and #/auth/callback?token=...
  const handleAuthHash = useCallback(async () => {
    const hash = window.location.hash || '';
    const match = hash.match(/^#\/auth\/(verify|callback)\??(.*)$/);
    if (!match) return false;
    const [, kind, query] = match;
    const params = new URLSearchParams(query);

    setSigningIn(true);
    let destination = '#app';
    try {
      if (kind === 'callback') {
        const token = params.get('token');
        if (token) {
          setToken(token);
          // Scrub the token from the URL immediately (replaceState, no new
          // history entry) so the bearer token isn't left reachable via Back.
          try {
            window.history.replaceState(null, document.title,
              window.location.pathname + window.location.search);
          } catch (_) { /* ignore */ }
        }
      } else if (kind === 'verify') {
        const ml = params.get('ml');
        if (ml) {
          const data = await apiJson('/api/auth/magic-link/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: ml }),
          });
          if (data.token) setToken(data.token);
        }
      }
      const signedInMe = await refreshMe();
      // New sign-ups (and anyone without an active plan/trial) go straight to
      // pricing so they can start their free trial; entitled users land in the app.
      if (signedInMe?.user && !signedInMe?.entitled) destination = '#/pricing';
    } catch (e) {
      // fall through — user lands signed-out
    } finally {
      setSigningIn(false);
      // Clear the sensitive hash, land wherever we resolved above.
      window.location.hash = destination;
    }
    return true;
  }, [refreshMe]);

  useEffect(() => {
    (async () => {
      try {
        const cfg = await (await fetch(getApiUrl('/api/config'))).json();
        setConfig(cfg);
        if (cfg.billingEnabled) {
          const handled = await handleAuthHash();
          if (!handled) await refreshMe(cfg);
        } else if (cfg.saasEnabled) {
          await refreshMe(cfg);
        }
      } catch (_) { /* config fetch failed — stay in BYOK */ }
      setLoading(false);
    })();
  }, [handleAuthHash, refreshMe]);

  const requestMagicLink = useCallback(async (email) => {
    const res = await apiFetch('/api/auth/magic-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (res.status === 429) throw new Error('Too many attempts. Try again in a few minutes.');
    if (!res.ok) throw new Error('Could not send sign-in link.');
    return true;
  }, []);

  const loginWithPassword = useCallback(async ({ email, password }) => {
    const data = await apiJson('/api/saas/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (data.access_token) setToken(data.access_token);
    const session = { user: data.user, workspace: data.workspace };
    setMe(session);
    return session;
  }, []);

  const signupWithPassword = useCallback(async ({ workspaceName, fullName, email, password }) => {
    const data = await apiJson('/api/saas/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workspace_name: workspaceName,
        full_name: fullName,
        email,
        password,
      }),
    });
    if (data.access_token) setToken(data.access_token);
    const session = { user: data.user, workspace: data.workspace };
    setMe(session);
    return session;
  }, []);

  const loginWithGoogle = useCallback(() => {
    window.location.href = getApiUrl('/api/auth/google');
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setMe(null);
  }, []);

  const value = {
    billingEnabled: config.billingEnabled,
    googleAuthEnabled: config.googleAuthEnabled,
    saasEnabled: config.saasEnabled,
    geminiConfigured: config.geminiConfigured,
    uploadPostConfigured: config.uploadPostConfigured,
    loading,
    signingIn,
    user: me?.user || null,
    workspace: me?.workspace || null,
    me,
    plan: me?.plan || null,
    entitled: !!me?.entitled,
    minutes: me?.minutes || null,
    isSignedIn: !!me?.user,
    // Managed = signed-in AND entitled (active plan or top-up credit).
    isManaged: !!(config.billingEnabled && me?.entitled),
    refreshMe,
    requestMagicLink,
    loginWithPassword,
    signupWithPassword,
    loginWithGoogle,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
