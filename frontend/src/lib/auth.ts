"use client";

import { useEffect, useState } from "react";

import { getAccessToken, logout } from "./api/client";
import { getMe } from "./api/endpoints";
import { useAsync } from "./api/hooks";

export interface CurrentUser {
  userId: string;
  orgId: string;
  role: string;
  scopes: string[];
  ready: boolean;
}

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  role: string;
}

const EMPTY: CurrentUser = {
  userId: "",
  orgId: "",
  role: "",
  scopes: [],
  ready: false,
};

function decodeJwt(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** Client-side current-user hook (decodes the access cookie JWT). */
export function useCurrentUser(): CurrentUser {
  const [user, setUser] = useState<CurrentUser>(EMPTY);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setUser({ ...EMPTY, ready: true });
      return;
    }
    const claims = decodeJwt(token);
    if (!claims) {
      setUser({ ...EMPTY, ready: true });
      return;
    }
    setUser({
      userId: String(claims.sub ?? ""),
      orgId: String(claims.org ?? ""),
      role: Array.isArray(claims.scopes) ? String(claims.scopes[0] ?? "") : String(claims.role ?? ""),
      scopes: Array.isArray(claims.scopes) ? (claims.scopes as string[]) : [],
      ready: true,
    });
  }, []);

  return user;
}

const EMPTY_PROFILE: UserProfile = { id: "", name: "", email: "", role: "" };

/** Fetch the real profile (display name, email) from /auth/me.
 *  Always returns a non-null `profile` (empty while loading / on error). */
export function useProfile(): {
  profile: UserProfile;
  loading: boolean;
  reload: () => void;
} {
  const { data, loading, reload } = useAsync(async () => {
    const me = await getMe();
    return {
      id: me.user_id,
      name: me.display_name || me.email,
      email: me.email,
      role: me.role,
    } satisfies UserProfile;
  }, []);

  return { profile: data ?? EMPTY_PROFILE, loading, reload };
}

export async function signOut(): Promise<void> {
  await logout();
  window.location.href = "/auth/v1/login";
}
