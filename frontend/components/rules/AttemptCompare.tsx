"use client";

import { useState } from "react";
import { type CompileAttempt, RulesApiError, pickAttempt } from "@/lib/rulesApi";

/** Round C (docs/rules) task 6 — compile attempts side by side.
 *
 * Every Rule Compiler attempt is KEPT on the rule (plan + explanation + when +
 * the operator's retry note); the rule's current plan is whichever attempt was
 * PICKED. Failed / needs-data attempts render their honest error and cannot be
 * picked — nothing is hidden and nothing broken is applied.
 */
export default function AttemptCompare({
  ruleKey,
  attempts,
  pickedAttemptNo,
  onPicked,
}: {
  ruleKey: string;
  attempts: CompileAttempt[];
  pickedAttemptNo?: number | null;
  onPicked?: () => void;
}) {
  const [busyNo, setBusyNo] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!attempts?.length) return null;

  const pick = async (n: number) => {
    setBusyNo(n);
    setError(null);
    try {
      await pickAttempt(ruleKey, n);
      onPicked?.();
    } catch (e) {
      setError(e instanceof RulesApiError ? e.message : String((e as Error)?.message || e));
    } finally {
      setBusyNo(null);
    }
  };

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, color: "var(--slate)", marginBottom: 6 }}>
        {attempts.length} compile attempt{attempts.length === 1 ? "" : "s"} — every attempt is kept; the
        current plan is the picked one.
      </div>
      {error ? (
        <div style={{ color: "var(--neg, #B3261E)", fontSize: 12.5, marginBottom: 6 }}>{error}</div>
      ) : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
        {attempts.map((a) => {
          const picked = pickedAttemptNo != null && a.attempt_no === pickedAttemptNo;
          const pickable = a.status === "COMPILED" && !picked;
          return (
            <div
              key={a.attempt_no}
              style={{
                border: picked ? "1.5px solid var(--navy)" : "1px solid var(--rule)",
                borderRadius: 5,
                padding: "10px 12px",
                background: "#fff",
              }}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                <b style={{ fontSize: 12.5 }}>Attempt {a.attempt_no}</b>
                <span className={a.status === "COMPILED" ? "chip pos" : "chip warn"}>
                  {a.status || "UNKNOWN"}
                </span>
                {picked ? <span className="chip on">Current plan</span> : null}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--slate)", marginBottom: 6 }}>
                {a.created_at || ""}
                {a.note ? (
                  <>
                    {" · "}
                    <span title="Operator note passed to the compiler as context">
                      note: &ldquo;{a.note}&rdquo;
                    </span>
                  </>
                ) : (
                  " · no note"
                )}
              </div>
              {a.explanation ? (
                <p style={{ fontSize: 12.5, margin: "0 0 6px" }}>{a.explanation}</p>
              ) : null}
              {a.compile_error ? (
                <p style={{ fontSize: 12, margin: "0 0 6px" }}>
                  <b>{a.status === "NEEDS_DATA" ? "Needs data:" : "Failed:"}</b> {a.compile_error}
                </p>
              ) : null}
              {a.plan != null ? (
                <pre
                  style={{
                    fontSize: 10.5,
                    lineHeight: 1.5,
                    background: "var(--paper, #F7F8FA)",
                    border: "1px solid var(--rule)",
                    borderRadius: 4,
                    padding: "6px 8px",
                    overflowX: "auto",
                    maxHeight: 220,
                    margin: 0,
                  }}
                >
                  {JSON.stringify(a.plan, null, 2)}
                </pre>
              ) : null}
              {pickable ? (
                <button
                  className="btn"
                  style={{ marginTop: 8 }}
                  disabled={busyNo != null}
                  onClick={() => pick(a.attempt_no)}
                >
                  {busyNo === a.attempt_no ? "Picking…" : "Pick this attempt"}
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
