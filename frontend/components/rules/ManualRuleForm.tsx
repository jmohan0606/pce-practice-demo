"use client";

import { useEffect, useMemo, useState } from "react";
import {
  type Advisor,
  type RuleDetail,
  approveRule,
  getAdvisors,
  getProductContribution,
  getTransitions,
} from "@/lib/api";
import { RulesApiError, createManualRule } from "@/lib/rulesApi";
import PlanView from "@/components/rules/PlanView";
import StatusChip from "@/components/rules/StatusChip";

/** Round C (docs/rules) task 5.4 — write a rule in plain English, no document.
 *
 * The "Generate a query?" choice is THE distinction of this round and must
 * never blur: yes → the Rule Compiler translates the statement into a plan
 * (shown for review before approval, reproducible figures); no → the rule is
 * guidance only — no plan by design, injected into the Insights Miner's
 * context, labelled "Guidance only, not computed", never an impact figure.
 */

const SEVERITIES = ["CRITICAL", "HIGH", "MODERATE", "LOW", "INFO"] as const;

type ProductGroup = { group_id: string; group_name: string };

export default function ManualRuleForm({ onCreated }: { onCreated?: () => void }) {
  const [ruleName, setRuleName] = useState("");
  const [statement, setStatement] = useState("");
  const [provenance, setProvenance] = useState("MANUALLY_WRITTEN_PRACTICE");
  const [appliesTo, setAppliesTo] = useState("ALL");
  const [appliesToKey, setAppliesToKey] = useState("");
  const [severity, setSeverity] = useState("MODERATE");
  const [driverLabel, setDriverLabel] = useState("");
  const [driverDefinition, setDriverDefinition] = useState("");
  const [generateQuery, setGenerateQuery] = useState(true);

  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [groups, setGroups] = useState<ProductGroup[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<RuleDetail | null>(null);
  const [approving, setApproving] = useState(false);
  const [approved, setApproved] = useState(false);

  // entity pickers: advisors from the advisors API; product groups from the
  // dashboard's product-contribution rows (latest transition)
  useEffect(() => {
    getAdvisors()
      .then((res) => setAdvisors(res.advisors ?? []))
      .catch(() => setAdvisors([]));
    getTransitions("all")
      .then((res) => {
        const last = res.transitions?.[res.transitions.length - 1];
        if (!last) return;
        return getProductContribution(last.from_month_id, last.to_month_id, "all", "all").then(
          (pc) => {
            const seen = new Map<string, string>();
            for (const section of pc.sections ?? [])
              for (const row of section.rows ?? [])
                if (!seen.has(row.group_id)) seen.set(row.group_id, row.group_name);
            setGroups([...seen.entries()].map(([group_id, group_name]) => ({ group_id, group_name })));
          },
        );
      })
      .catch(() => setGroups([]));
  }, []);

  const needsKey = appliesTo === "ADVISOR" || appliesTo === "PRODUCT";
  const canSubmit = useMemo(
    () => !busy && ruleName.trim().length > 0 && statement.trim().length > 0 && driverLabel.trim().length > 0,
    [busy, ruleName, statement, driverLabel],
  );

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setCreated(null);
    setApproved(false);
    try {
      const res = await createManualRule({
        rule_name: ruleName.trim(),
        statement: statement.trim(),
        provenance,
        applies_to: appliesTo,
        applies_to_key: needsKey && appliesToKey ? appliesToKey : null,
        severity,
        driver_label: driverLabel.trim(),
        driver_definition: driverDefinition.trim(),
        generate_query: generateQuery,
      });
      setCreated(res.rule);
      onCreated?.();
    } catch (e) {
      setError(
        e instanceof RulesApiError
          ? e.status === 0 || e.status === 404
            ? "The manual-rule service is not available yet — nothing was created."
            : e.message
          : String((e as Error)?.message || e),
      );
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    if (!created?.rule_key) return;
    setApproving(true);
    setError(null);
    try {
      await approveRule(created.rule_key, "operator");
      setApproved(true);
      onCreated?.();
    } catch (e) {
      setError(String((e as Error)?.message || e));
    } finally {
      setApproving(false);
    }
  };

  const fieldStyle = {
    width: "100%",
    font: "inherit",
    fontSize: 13,
    border: "1px solid var(--rule)",
    borderRadius: 4,
    padding: "7px 9px",
    background: "#fff",
  } as const;

  return (
    <div>
      <label className="fld">Rule name</label>
      <input
        style={fieldStyle}
        value={ruleName}
        onChange={(e) => setRuleName(e.target.value)}
        placeholder="e.g. Fee Schedule Variance"
      />
      <label className="fld" style={{ marginTop: 10 }}>
        Statement — plain English
      </label>
      <textarea
        style={{ ...fieldStyle, minHeight: 74, resize: "vertical" }}
        value={statement}
        onChange={(e) => setStatement(e.target.value)}
        placeholder="Describe the rule the way you would explain it to a colleague — thresholds included."
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
        <div>
          <label className="fld">Written by</label>
          <select style={fieldStyle} value={provenance} onChange={(e) => setProvenance(e.target.value)}>
            <option value="MANUALLY_WRITTEN_PRACTICE">MANUALLY WRITTEN-PRACTICE</option>
            <option value="MANUALLY_WRITTEN_TECH">MANUALLY WRITTEN-TECH</option>
          </select>
        </div>
        <div>
          <label className="fld">Severity</label>
          <select style={fieldStyle} value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s.charAt(0) + s.slice(1).toLowerCase()}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="fld">Applies to</label>
          <select
            style={fieldStyle}
            value={appliesTo}
            onChange={(e) => {
              setAppliesTo(e.target.value);
              setAppliesToKey("");
            }}
          >
            <option value="ALL">Everywhere (default)</option>
            <option value="PRACTICE">Practice (firm level only)</option>
            <option value="ADVISOR">One advisor</option>
            <option value="PRODUCT">One product group</option>
            <option value="COMPENSATION_ENGINE">Compensation Engine (calculation-level)</option>
          </select>
        </div>
        <div>
          {appliesTo === "ADVISOR" ? (
            <>
              <label className="fld">Advisor</label>
              <select style={fieldStyle} value={appliesToKey} onChange={(e) => setAppliesToKey(e.target.value)}>
                <option value="">Any advisor (advisor-level)</option>
                {advisors.map((a) => (
                  <option key={a.advisor_sid} value={a.advisor_sid}>
                    {a.advisor_name ? `${a.advisor_name} (${a.advisor_sid})` : a.advisor_sid}
                  </option>
                ))}
              </select>
            </>
          ) : appliesTo === "PRODUCT" ? (
            <>
              <label className="fld">Product group</label>
              <select style={fieldStyle} value={appliesToKey} onChange={(e) => setAppliesToKey(e.target.value)}>
                <option value="">Any product group</option>
                {groups.map((g) => (
                  <option key={g.group_id} value={g.group_id}>
                    {g.group_name || g.group_id}
                  </option>
                ))}
              </select>
            </>
          ) : null}
        </div>
        <div>
          <label className="fld">Driver label</label>
          <input
            style={fieldStyle}
            value={driverLabel}
            onChange={(e) => setDriverLabel(e.target.value)}
            placeholder="e.g. Fee Schedule Variance"
          />
        </div>
        <div>
          <label className="fld">Driver definition</label>
          <input
            style={fieldStyle}
            value={driverDefinition}
            onChange={(e) => setDriverDefinition(e.target.value)}
            placeholder="What this driver means to a business reader"
          />
        </div>
      </div>
      <div style={{ marginTop: 12, padding: "10px 12px", border: "1px solid var(--rule)", borderRadius: 5 }}>
        <label className="fld" style={{ marginBottom: 6 }}>
          Generate a query?
        </label>
        <label style={{ display: "flex", gap: 8, fontSize: 12.5, alignItems: "flex-start", marginBottom: 6 }}>
          <input type="radio" checked={generateQuery} onChange={() => setGenerateQuery(true)} />
          <span>
            <b>Yes</b> — the Rule Compiler translates the statement into a query plan, shown here for review
            before approval. A rule with a plan produces reproducible figures.
          </span>
        </label>
        <label style={{ display: "flex", gap: 8, fontSize: 12.5, alignItems: "flex-start" }}>
          <input type="radio" checked={!generateQuery} onChange={() => setGenerateQuery(false)} />
          <span>
            <b>No</b> — <b>Guidance only, not computed.</b> The statement shapes the AI&rsquo;s investigation;
            it is never evaluated as a query and can never produce a computed impact figure.
          </span>
        </label>
      </div>
      <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn primary" disabled={!canSubmit} onClick={submit}>
          {busy ? (generateQuery ? "Creating & compiling…" : "Creating…") : "Create rule"}
        </button>
        {error ? <span style={{ color: "var(--neg, #B3261E)", fontSize: 12.5 }}>{error}</span> : null}
      </div>
      {created ? (
        <div style={{ marginTop: 14, borderTop: "1px solid var(--rule)", paddingTop: 12 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
            <b style={{ fontSize: 13 }}>{created.rule_name}</b>
            <StatusChip status={created.status} active={created.active} activeReason={created.active_reason} />
          </div>
          {created.needs_data_reason ? (
            <p style={{ fontSize: 12.5, margin: "4px 0" }}>
              <b>Needs data we don&rsquo;t have:</b> {created.needs_data_reason}
            </p>
          ) : null}
          {created.compile_error && !created.needs_data_reason && !created.natural_language_only ? (
            <p style={{ fontSize: 12.5, margin: "4px 0" }}>
              <b>Compile failed honestly:</b> {created.compile_error}
            </p>
          ) : null}
          <PlanView
            plan={created.plan}
            explanation={created.explanation}
            naturalLanguageOnly={created.natural_language_only}
          />
          {created.status === "COMPILED" && created.plan ? (
            <button className="btn" disabled={approving || approved} onClick={approve}>
              {approved ? "Approved for next publish" : approving ? "Approving…" : "Approve this plan"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
