/** Round C (docs/rules) — a compiled plan with its plain-English explanation.
 * A rule without a plan states which kind of no-plan it is, honestly:
 * guidance-only (by design) vs not-yet-compiled. Never renders an invented
 * summary — the JSON is the plan, the explanation is the compiler's. */
export default function PlanView({
  plan,
  explanation,
  naturalLanguageOnly,
}: {
  plan?: unknown;
  explanation?: string | null;
  naturalLanguageOnly?: boolean;
}) {
  if (!plan) {
    return (
      <p className="planNote" style={{ fontSize: 12.5, color: "var(--slate)", margin: "6px 0" }}>
        {naturalLanguageOnly
          ? "Guidance only, not computed — this rule has no query by design; its statement shapes the AI's attention while investigating, and it can never produce a computed impact figure."
          : "No compiled plan yet — run the Rule Compiler."}
      </p>
    );
  }
  return (
    <div className="planview" style={{ margin: "6px 0" }}>
      {explanation ? (
        <p style={{ fontSize: 12.5, margin: "0 0 6px" }}>{explanation}</p>
      ) : null}
      <pre
        style={{
          fontSize: 11,
          lineHeight: 1.5,
          background: "var(--paper, #F7F8FA)",
          border: "1px solid var(--rule)",
          borderRadius: 4,
          padding: "8px 10px",
          overflowX: "auto",
          margin: 0,
        }}
      >
        {JSON.stringify(plan, null, 2)}
      </pre>
    </div>
  );
}
