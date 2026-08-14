/** Round A2B task 7 — feature-flags API client (Subagent C's surface; lib/api.ts
 * is owned elsewhere and never edited from here). */

import { ApiError } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "http://localhost:8002";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, `API unreachable at ${API_BASE}`);
  }
  if (!response.ok) {
    let detail = `${response.status} for ${path}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export interface FlagCost {
  amount_usd: number | null;
  unit: string;
  history_runs: number;
  /** e.g. "estimate, feature not built" for chat. */
  note: string | null;
}
export interface FlagNote {
  when: string;
  by: string;
  reason: string;
}
export interface FlagRow {
  key: string;
  name: string;
  description: string;
  group: string;
  parent: string | null;
  always_on: boolean;
  dep: string | null;
  enabled: boolean;
  effective_enabled: boolean;
  note: FlagNote | null;
  cost: FlagCost | null;
}
export interface FlagsResponse {
  flags: FlagRow[];
  on_count: number;
  total: number;
  ceiling: number;
  groups: { id: string; name: string }[];
  presets: { id: string; name: string; description: string; on_count: number; total: number }[];
}
export interface FlagHistoryRow {
  when: string;
  flag: string;
  flag_name: string;
  enabled: boolean;
  by: string;
  reason: string;
}

export function getFlags(): Promise<FlagsResponse> {
  return request("/api/flags");
}
export function patchFlag(
  key: string,
  enabled: boolean,
  reason?: string,
  by?: string,
): Promise<FlagRow> {
  return request(`/api/flags/${encodeURIComponent(key)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, reason: reason ?? null, by: by ?? null }),
  });
}
export function applyPreset(name: string, by?: string): Promise<FlagsResponse> {
  return request(`/api/flags/preset/${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ by: by ?? "operator" }),
  });
}
export function getFlagHistory(): Promise<{ history: FlagHistoryRow[] }> {
  return request("/api/flags/history");
}
