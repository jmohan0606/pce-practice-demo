"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/** Round A2B task 6 — the insights page moved to /advisor (renamed
 * "iPerform Advisor AI Insights"). This route stays alive as a client
 * redirect preserving ?sid=, because <AdvisorLink> targets /advisor?sid=
 * and old bookmarks target /insights. */
function RedirectInner() {
  const router = useRouter();
  const params = useSearchParams();
  useEffect(() => {
    const sid = params.get("sid");
    router.replace(sid ? `/advisor?sid=${encodeURIComponent(sid)}` : "/advisor");
  }, [router, params]);
  return (
    <div style={{ padding: 24, color: "var(--slate)", fontSize: "13px" }}>
      This page moved to iPerform Advisor AI Insights — redirecting…
    </div>
  );
}

export default function InsightsRedirect() {
  return (
    <Suspense fallback={null}>
      <RedirectInner />
    </Suspense>
  );
}
