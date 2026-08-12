"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  type RuleDetail,
  type RuleVersion,
  approveRule,
  compileRule,
  editRule,
  getRuleVersions,
  getRulesDetailed,
  publishRules,
} from "@/lib/api";
import Chip from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";

/** Rule Set Versions (4.6): expanding a version lists every rule — name, plain
 * description, source citation, compiled query, status. Edit never mutates:
 * it creates a new draft, approves it, and publishes the NEXT version. */
export default function RuleVersionsPage() {
  const [versions, setVersions] = useState<RuleVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rulesByVersion, setRulesByVersion] = useState<Record<string, RuleDetail[]>>({});
  const [openVersion, setOpenVersion] = useState<string | null>(null);
  const [editing, setEditing] = useState<RuleDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(() => {
    getRuleVersions()
      .then((res) => {
        setVersions([...(res.versions ?? [])].sort((a, b) => b.version_no - a.version_no));
        setError(null);
      })
      .catch((e) => {
        setVersions(null);
        setError(
          e instanceof ApiError && e.status === 404
            ? "The rule service (B3) is not available yet."
            : String(e?.message || e),
        );
      });
  }, []);

  useEffect(reload, [reload]);

  const toggle = (versionId: string) => {
    if (openVersion === versionId) {
      setOpenVersion(null);
      return;
    }
    setOpenVersion(versionId);
    if (!rulesByVersion[versionId]) {
      getRulesDetailed(versionId)
        .then((res) => setRulesByVersion((prev) => ({ ...prev, [versionId]: res.rules })))
        .catch((e) => setError(String(e?.message || e)));
    }
  };

  const submitEdit = async (rule: RuleDetail, changes: Record<string, unknown>) => {
    setBusy("editing…");
    setNotice(null);
    try {
      const { rule: draft } = await editRule(rule.rule_key ?? rule.rule_code, changes);
      // Round E lifecycle: a changed statement invalidates the plan — the Rule
      // Compiler agent recompiles the new draft before it can be approved.
      setBusy("compiling the new draft (Rule Compiler agent)…");
      const { rule: compiled } = await compileRule(draft.rule_key ?? draft.rule_code);
      if ((compiled.status || "").toUpperCase() !== "COMPILED") {
        setNotice(
          `The edited draft did not compile (${compiled.status}): ` +
            `${compiled.needs_data_reason || compiled.compile_error || "see the draft pool"}. ` +
            "It stays in Documents & Rules until resolved — no version was published.",
        );
        setEditing(null);
        setBusy(null);
        return;
      }
      setBusy("approving the new draft…");
      await approveRule(draft.rule_key ?? draft.rule_code);
      setBusy("publishing the next version…");
      const { version } = await publishRules("operator", `edit of ${rule.rule_code}`);
      setNotice(
        `v${version.version_no} published with the edited rule — the original version is unchanged.`,
      );
      setEditing(null);
      setRulesByVersion({});
      setOpenVersion(null);
      reload();
    } catch (e) {
      setNotice(`Edit failed: ${String((e as Error)?.message || e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section>
      <PageHeader title="Rule Set Versions" meta="Every insight records the version that produced it" />
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Rule Set Versions</h2>
            <p>
              Expand a version to see every rule it contains. Versions are superseded, never
              deleted; edits mint a new version.
            </p>
          </div>
        </div>
        <div className="card-b">
          {notice ? (
            <div className="note" style={{ marginBottom: 12, border: "1px solid var(--rule)", borderRadius: 5 }}>
              {notice}
            </div>
          ) : null}
          {versions && versions.length ? (
            <ul className="vers">
              {versions.map((v) => {
                const versionId = v.version_id ?? String(v.version_no);
                const status = (v.status || "").toUpperCase();
                const current = status === "PUBLISHED";
                const open = openVersion === versionId;
                const rules = rulesByVersion[versionId];
                return (
                  <li key={versionId} className={current ? "cur" : undefined} style={{ display: "block" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 14, alignItems: "flex-start" }}>
                      <div>
                        <b>
                          v{v.version_no}
                          {v.published_at ? ` · Published ${v.published_at}` : v.created_at ? ` · ${v.created_at}` : ""}
                        </b>
                        <div className="meta">
                          {[
                            v.rule_count != null ? `${v.rule_count} rules` : null,
                            v.approved_by ? `approved by ${v.approved_by}` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                          {v.notes ? (
                            <>
                              <br />
                              {v.notes}
                            </>
                          ) : null}
                        </div>
                      </div>
                      <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {current ? (
                          <Chip variant="pos">In Use</Chip>
                        ) : v.version_no === 0 ? (
                          <Chip variant="derived">Team Written</Chip>
                        ) : (
                          <Chip variant="tag">Superseded</Chip>
                        )}
                        <div style={{ marginTop: 6 }}>
                          <button className="btn" onClick={() => toggle(versionId)}>
                            {open ? "Collapse" : `View ${v.rule_count ?? ""} rules`}
                          </button>
                        </div>
                      </div>
                    </div>
                    {open ? (
                      rules ? (
                        <div style={{ marginTop: 12 }}>
                          {rules.map((r) => (
                            <RuleRow
                              key={r.rule_code}
                              rule={r}
                              canEdit={current}
                              busy={busy}
                              editing={editing?.rule_code === r.rule_code ? editing : null}
                              onEdit={() => setEditing(r)}
                              onCancel={() => setEditing(null)}
                              onSubmit={submitEdit}
                            />
                          ))}
                        </div>
                      ) : (
                        <div className="meta" style={{ marginTop: 10 }}>
                          Loading rules…
                        </div>
                      )
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState
              title={error ? "Versions Unavailable" : "No Rule Set Versions Yet"}
              message={error ?? "Published rule set versions will appear here."}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function RuleRow({
  rule,
  canEdit,
  busy,
  editing,
  onEdit,
  onCancel,
  onSubmit,
}: {
  rule: RuleDetail;
  canEdit: boolean;
  busy: string | null;
  editing: RuleDetail | null;
  onEdit: () => void;
  onCancel: () => void;
  onSubmit: (rule: RuleDetail, changes: Record<string, unknown>) => void;
}) {
  const citation = rule.citations?.[0];
  const status = (rule.status || "").toUpperCase();
  const [form, setForm] = useState({
    rule_name: rule.rule_name ?? "",
    statement: rule.statement ?? rule.plain_description ?? "",
    worked_example: rule.worked_example ?? "",
  });
  return (
    <div className={`rule${status === "NEEDS_INPUT" ? " needs" : ""}`}>
      <div className="rule-h">
        <div>
          <div className="rule-t">
            {rule.rule_name} <span className="pfx">({rule.rule_code})</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {rule.kind ? <Chip variant="tag">{rule.kind}</Chip> : null}
          <Chip variant={status === "PUBLISHED" ? "pos" : status === "NEEDS_INPUT" ? "derived" : "tag"}>
            {status || "?"}
          </Chip>
          {canEdit ? (
            <button className="btn" onClick={editing ? onCancel : onEdit} disabled={busy !== null}>
              {editing ? "Cancel" : "Edit → new version"}
            </button>
          ) : null}
        </div>
      </div>
      {/* 6.3: the rule's plain-English statement */}
      <div className="rule-d">{rule.statement || rule.plain_description}</div>
      {rule.worked_example ? (
        <div className="eg">
          Example — <b>{rule.worked_example}</b>
        </div>
      ) : null}
      {citation ? (
        <div className="eg">
          <b>Source:</b> {citation.document_name || rule.document_id || "operator-specified"}
          {citation.page_no != null ? ` · p.${citation.page_no}` : ""}
          {citation.section_path ? ` · ${citation.section_path}` : ""}
          {citation.excerpt ? (
            <>
              <br />
              <span style={{ fontStyle: "italic" }}>&ldquo;{citation.excerpt}&rdquo;</span>
            </>
          ) : null}
        </div>
      ) : (
        <div className="eg">
          <b>Source:</b> {rule.provenance === "OPERATOR_SPECIFIED" ? "operator-specified (no document)" : "no citation recorded"}
        </div>
      )}
      {/* 6.3: the compiled query with its plain-English explanation */}
      <details className="tech">
        <summary>Query this compiles to</summary>
        {rule.explanation ? (
          <div className="eg" style={{ marginTop: 8, marginBottom: 0 }}>
            {rule.explanation}
          </div>
        ) : null}
        <pre>
          {rule.plan
            ? JSON.stringify(rule.plan, null, 2)
            : rule.population || rule.compute || rule.trigger
              ? `population: ${rule.population || "—"}\ncompute:    ${rule.compute || "—"}\ntrigger:    ${rule.trigger || "—"}` +
                (rule.attribute ? `\nattribute:  ${rule.attribute}` : "")
              : "no compiled plan"}
          {rule.compiled === false ? `\n\nDOES NOT COMPILE: ${rule.compile_error ?? "unknown"}` : ""}
        </pre>
      </details>
      {rule.needs_data_reason ? (
        <div className="eg">
          <b>Needs data we don&rsquo;t have:</b> {rule.needs_data_reason}
        </div>
      ) : null}
      {rule.missing ? (
        <div className="eg">
          <b>Needs a value:</b> {rule.missing}
        </div>
      ) : null}
      {editing ? (
        <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
          {(["rule_name", "statement", "worked_example"] as const).map((field) => (
            <label key={field} style={{ fontSize: 12, color: "var(--slate)" }}>
              {field === "statement" ? "statement (plain English — the Rule Compiler compiles this)" : field}
              <textarea
                value={form[field]}
                onChange={(e) => setForm((prev) => ({ ...prev, [field]: e.target.value }))}
                rows={field === "statement" ? 4 : field === "worked_example" ? 2 : 1}
                style={{
                  width: "100%",
                  font: "12px/1.5 ui-monospace,Menlo,Consolas,monospace",
                  border: "1px solid var(--rule)",
                  borderRadius: 4,
                  padding: "6px 8px",
                  marginTop: 3,
                }}
              />
            </label>
          ))}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              className="btn primary"
              disabled={busy !== null}
              onClick={() => {
                const changes: Record<string, unknown> = {};
                if (form.rule_name !== (rule.rule_name ?? "")) changes.rule_name = form.rule_name;
                if (form.statement !== (rule.statement ?? rule.plain_description ?? ""))
                  changes.statement = form.statement;
                if (form.worked_example !== (rule.worked_example ?? ""))
                  changes.worked_example = form.worked_example;
                onSubmit(rule, changes);
              }}
            >
              {busy ?? "Save as new version"}
            </button>
            <span style={{ fontSize: 12, color: "var(--slate)" }}>
              Saving creates a new draft, recompiles it with the Rule Compiler, approves it, and
              publishes the next version — this version is never mutated.
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
