"use client";

/** Round A2B task 7 — frontend flag enforcement.
 *
 * <Gated flag="...">{children}</Gated> renders null while the flag is off —
 * the children are UNMOUNTED, so their effects and fetches never fire (OFF
 * means the queries do not run, not CSS-hiding). While flags are still
 * loading, children render (the backend 409s are the hard gate); an unknown
 * flag key renders nothing and logs, never guesses.
 *
 * Flags are fetched once per session and shared; refreshFlags() invalidates
 * after the Settings page writes.
 */

import { type ReactNode, useEffect, useState } from "react";
import { type FlagsResponse, getFlags } from "@/lib/flagsApi";

let cached: FlagsResponse | null = null;
let inflight: Promise<FlagsResponse> | null = null;
const listeners = new Set<(f: FlagsResponse | null) => void>();

function load(): void {
  if (cached || inflight) return;
  inflight = getFlags()
    .then((f) => {
      cached = f;
      listeners.forEach((fn) => fn(f));
      return f;
    })
    .catch((e) => {
      inflight = null; // allow a retry on the next mount
      throw e;
    });
  inflight.catch(() => undefined);
}

/** Invalidate the session cache (Settings page calls this after each write). */
export function refreshFlags(): void {
  cached = null;
  inflight = null;
  load();
}

export function useFeatureFlags(): FlagsResponse | null {
  const [flags, setFlags] = useState<FlagsResponse | null>(cached);
  useEffect(() => {
    if (cached) setFlags(cached);
    const fn = (f: FlagsResponse | null) => setFlags(f);
    listeners.add(fn);
    load();
    return () => {
      listeners.delete(fn);
    };
  }, []);
  return flags;
}

/** true / false once loaded; null while the flags are still loading. */
export function useFlag(key: string): boolean | null {
  const flags = useFeatureFlags();
  if (!flags) return null;
  const row = flags.flags.find((f) => f.key === key);
  if (!row) {
    // unknown key: never guess — treat as off and say so in the console
    console.warn(`useFlag: unknown feature flag '${key}'`);
    return false;
  }
  return row.effective_enabled;
}

/** Children unmounted (=> their fetches never fire) while the flag is off. */
export function Gated({ flag, children }: { flag: string; children: ReactNode }) {
  const on = useFlag(flag);
  if (on === false) return null;
  return <>{children}</>;
}
