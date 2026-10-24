import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { RequestAuthHeaders } from "./api";

export type ActorRole = "OWNER" | "MANAGER" | "STAFF";

export interface ActorProfile {
  actorId: string;
  role: ActorRole;
  label: string;
  description: string;
}

export const KNOWN_ACTORS: ActorProfile[] = [
  {
    actorId: "user_owner_01",
    role: "OWNER",
    label: "Owner",
    description: "Full SME business owner authority",
  },
  {
    actorId: "user_manager_01",
    role: "MANAGER",
    label: "Manager",
    description: "Operational management and proposal approval authority",
  },
  {
    actorId: "user_staff_01",
    role: "STAFF",
    label: "Staff",
    description: "Operational staff with redacted financial views",
  },
  {
    actorId: "owner_01",
    role: "OWNER",
    label: "Owner (owner_01)",
    description: "Full SME business owner authority",
  },
  {
    actorId: "manager_01",
    role: "MANAGER",
    label: "Manager (manager_01)",
    description: "Operational management and proposal approval authority",
  },
  {
    actorId: "staff_01",
    role: "STAFF",
    label: "Staff (staff_01)",
    description: "Operational staff with redacted financial views",
  },
];

export interface AuthContextValue {
  tenantId: string;
  setTenantId: (tenantId: string) => void;
  actorId: string;
  actorRole: ActorRole;
  setActorId: (actorId: string) => void;
  authHeaders: RequestAuthHeaders;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export interface AuthProviderProps {
  children: ReactNode;
  initialTenantId?: string;
  initialActorId?: string;
}

export function AuthProvider({
  children,
  initialTenantId = "tenant_demo_01",
  initialActorId = "user_owner_01",
}: AuthProviderProps) {
  const [tenantId, setTenantId] = useState(initialTenantId);
  const [actorId, setActorId] = useState(initialActorId);

  const actorRole = useMemo<ActorRole>(() => {
    const found = KNOWN_ACTORS.find((a) => a.actorId === actorId);
    if (found) return found.role;
    const lower = actorId.toLowerCase();
    if (lower.includes("owner")) return "OWNER";
    if (lower.includes("manager")) return "MANAGER";
    return "STAFF";
  }, [actorId]);

  const authHeaders = useMemo<RequestAuthHeaders>(() => {
    return {
      tenantId,
      actorId,
    };
  }, [tenantId, actorId]);

  const value = useMemo<AuthContextValue>(
    () => ({
      tenantId,
      setTenantId,
      actorId,
      actorRole,
      setActorId,
      authHeaders,
    }),
    [tenantId, actorId, actorRole, authHeaders],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}
