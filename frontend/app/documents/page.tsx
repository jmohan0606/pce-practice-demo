"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type DocumentInfo,
  type ExtractionGap,
  type ExtractionSummary,
  type RuleDetail,
  getDocuments,
  getExtractionSummary,
  getRulesDetailed,
  uploadDocuments,
} from "@/lib/api";
import {
  type CompileAttempt,
  DOCUMENT_CATEGORIES,
  type DocumentCategory,
  EXTRACTING_CATEGORIES,
  RulesApiError,
  recompileRule,
  setDocumentCategory,
} from "@/lib/rulesApi";
import Chip, { type ChipVariant } from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import SourceLink from "@/components/SourceLink";
import AppliesToChip from "@/components/rules/AppliesToChip";
import AttemptCompare from "@/components/rules/AttemptCompare";
import ManualRuleForm from "@/components/rules/ManualRuleForm";
import PlanView from "@/components/rules/PlanView";
import ProvenanceChip from "@/components/rules/ProvenanceChip";
import RuleListManager from "@/components/rules/RuleListManager";
import SeverityChip from "@/components/rules/SeverityChip";
import StatusChip from "@/components/rules/StatusChip";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8002";

// Round C (docs/rules) 3.1 category labels — only PLAN and FAQ feed the extractor.
const CATEGORY_LABELS: Record<DocumentCategory, string> = {
  PLAN: "PLAN — rules are extracted",
  GUIDANCE: "GUIDANCE — coaching, search only",
  PLAYBOOK: "PLAYBOOK — process, search only",
  TRAINING: "TRAINING — reference, search only",
  FAQ: "FAQ — rules are extracted",
  OTHER: "OTHER — indexed, search only",
};

type DocRow = DocumentInfo & { document_category?: string; document_type?: string };
type DraftRule = RuleDetail & {
  compile_attempts?: CompileAttempt[];
  picked_attempt_no?: number | null;
};

function statusChip(status?: string): { variant: ChipVariant; label: string } {
  switch ((status || "").toLowerCase()) {
    case "indexed":
      return { variant: "pos", label: "Indexed" };
    case "failed":
      return { variant: "neg", label: "Failed" };
    case "uploaded":
    case "parsed":
    case "chunked":
    case "embedded":
      return { variant: "derived", label: (status as string)[0].toUpperCase() + (status as string).slice(1) };
    default:
      return { variant: "tag", label: status || "Unknown" };
  }
}

/** 6.4 — the extraction outcome, gaps included. Silent gaps are how the
 * client environment fails without anyone noticing: every NEEDS_INPUT /
 * NEEDS_DATA rule is countable here and expandable to its stated reason. */
function ExtractionSummaryBlock({ summary }: { summary: ExtractionSummary }) {
  const gapList = (title: string, gaps: ExtractionGap[]) => (
    <details className="tech" style={{ marginTop: 6 }}>
      <summary>
        {gaps.length} {title}
      </summary>
      <div style={{ marginTop: 6 }}>
        {gaps.map((g) => (
          <div key={g.rule_key} className="eg" style={{ marginBottom: 6 }}>
            <b>{g.rule_code || g.rule_key}</b> — {g.reason || "no reason recorded"}
          </div>
        ))}
      </div>
    </details>
  );
  return (
    <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5, marginBottom: 14 }}>
      <b>
        {summary.extracted} extracted · {summary.compiled} compiled · {summary.needs_input.length} need a
        value · {summary.needs_data.length} need data we don&rsquo;t have
        {summary.draft ? ` · ${summary.draft} not yet compiled` : ""}
      </b>
      {summary.needs_input.length ? gapList("need a value the document does not state", summary.needs_input) : null}
      {summary.needs_data.length ? gapList("need data the schema cannot express", summary.needs_data) : null}
    </div>
  );
}

/** Documents & Rules — Round C (docs/rules): six upload categories, per-row
 * category editing with an extraction offer, manual rule authoring, rule list
 * management, and compile-attempt retry/compare on draft rules. Endpoints
 * built in parallel degrade to an honest message, never a crash. */
export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocRow[] | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [rules, setRules] = useState<DraftRule[] | null>(null);
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ExtractionSummary | null>(null);
  const [uploading, setUploading] = useState(false);
  // 3.1: category chosen at upload, defaulting PLAN. Only PLAN and FAQ feed
  // the Rule Extractor; every category is chunked, embedded and searchable.
  const [docType, setDocType] = useState<DocumentCategory>("PLAN");
  const [categoryBusy, setCategoryBusy] = useState<string | null>(null);
  const [extractionOffer, setExtractionOffer] = useState<string | null>(null);
  const [extractBusy, setExtractBusy] = useState(false);
  const [docActionError, setDocActionError] = useState<string | null>(null);
  // task 6 — retry note per rule
  const [retryFor, setRetryFor] = useState<string | null>(null);
  const [retryNote, setRetryNote] = useState("");
  const [retryBusy, setRetryBusy] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refreshDocuments = useCallback(() => {
    getDocuments()
      .then((res) => {
        setDocuments((res.documents ?? []) as DocRow[]);
        setDocumentsError(null);
      })
      .catch((e) => {
        setDocuments(null);
        setDocumentsError(
          e instanceof ApiError && e.status === 404
            ? "The document service (B2) is not available yet."
            : String(e?.message || e),
        );
      });
  }, []);

  const refreshRules = useCallback(() => {
    // 6.4: the counts come from the API — never hardcoded
    getExtractionSummary().then(setExtraction).catch(() => setExtraction(null));
    getRulesDetailed("drafts")
      .then((res) => {
        setRules((res.rules ?? []) as DraftRule[]);
        setRulesError(null);
      })
      .catch((e) => {
        setRules(null);
        setRulesError(
          e instanceof ApiError && e.status === 404
            ? "The rule service (B3) is not available yet."
            : String(e?.message || e),
        );
      });
  }, []);

  useEffect(() => {
    refreshDocuments();
    refreshRules();
  }, [refreshDocuments, refreshRules]);

  const onFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || !files.length) return;
      setUploading(true);
      try {
        // lib/api's uploadDocuments signature predates the six-category
        // contract; the backend accepts all six (validated server-side).
        await uploadDocuments(Array.from(files), docType as "PLAN" | "GUIDANCE");
        refreshDocuments();
      } catch (e) {
        setDocumentsError(String((e as Error)?.message || e));
      } finally {
        setUploading(false);
      }
    },
    [refreshDocuments, docType],
  );

  const changeCategory = useCallback(
    async (documentId: string, category: DocumentCategory) => {
      setCategoryBusy(documentId);
      setDocActionError(null);
      setExtractionOffer(null);
      try {
        const res = await setDocumentCategory(documentId, category);
        // 3.1: changing to PLAN or FAQ offers to run extraction — offered,
        // never auto-run.
        if (res.extraction_offered) setExtractionOffer(documentId);
        refreshDocuments();
      } catch (e) {
        setDocActionError(
          e instanceof RulesApiError
            ? e.status === 0 || e.status === 404
              ? "Category editing is not available yet — the document category service has not been deployed."
              : e.message
            : String((e as Error)?.message || e),
        );
      } finally {
        setCategoryBusy(null);
      }
    },
    [refreshDocuments],
  );

  const runExtraction = useCallback(
    async (documentId: string) => {
      setExtractBusy(true);
      setDocActionError(null);
      try {
        const response = await fetch(
          `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/extract-rules`,
          { method: "POST" },
        );
        if (!response.ok) {
          let detail = `${response.status} while running extraction`;
          try {
            const parsed = await response.json();
            if (parsed?.detail) detail = String(parsed.detail);
          } catch {
            /* keep the status message */
          }
          throw new Error(detail);
        }
        setExtractionOffer(null);
        refreshDocuments();
        refreshRules();
      } catch (e) {
        setDocActionError(String((e as Error)?.message || e));
      } finally {
        setExtractBusy(false);
      }
    },
    [refreshDocuments, refreshRules],
  );

  const retry = useCallback(
    async (ruleKey: string) => {
      setRetryBusy(true);
      setRetryError(null);
      try {
        await recompileRule(ruleKey, retryNote);
        setRetryFor(null);
        setRetryNote("");
        refreshRules();
      } catch (e) {
        setRetryError(
          e instanceof RulesApiError
            ? e.status === 0 || e.status === 404
              ? "Retry is not available yet — the recompile service has not been deployed."
              : e.message
            : String((e as Error)?.message || e),
        );
      } finally {
        setRetryBusy(false);
      }
    },
    [retryNote, refreshRules],
  );

  const ruleCard = (rule: DraftRule) => {
    const status = (rule.status || "DRAFT").toUpperCase();
    const cls = status === "NEEDS_INPUT" || status === "NEEDS_DATA" ? "needs" : "draft";
    const citation = rule.citations?.[0];
    const key = rule.rule_key || rule.rule_code;
    const canRetry =
      !!rule.rule_key && (status === "DRAFT" || status === "COMPILED" || status === "NEEDS_DATA") && !rule.natural_language_only;
    return (
      <div className={`rule ${cls}`} key={key}>
        <div className="rule-h">
          <div className="rule-t">{rule.rule_name || rule.rule_code}</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <SeverityChip severity={rule.severity} />
            <AppliesToChip appliesTo={rule.applies_to} appliesToKey={rule.applies_to_key} />
            <ProvenanceChip provenance={rule.provenance} provenanceLabel={rule.provenance_label} />
            <StatusChip status={rule.status} active={rule.active} activeReason={rule.active_reason} />
          </div>
        </div>
        {rule.statement || rule.plain_description ? (
          <div className="rule-d">{rule.statement || rule.plain_description}</div>
        ) : null}
        {rule.worked_example ? (
          <div className="eg">
            Example — <b>{rule.worked_example}</b>
          </div>
        ) : null}
        {rule.missing || rule.unclear_notes ? (
          <div className="eg">
            <b>Needs a value:</b> {rule.missing || rule.unclear_notes} <b>No value has been assumed.</b>
          </div>
        ) : null}
        {rule.needs_data_reason ? (
          <div className="eg">
            <b>Needs data we don&rsquo;t have:</b> {rule.needs_data_reason}
          </div>
        ) : null}
        {/* Guidance-only vs computed must never blur: PlanView labels a
            plan-less natural-language rule "Guidance only, not computed". */}
        {rule.plan || rule.natural_language_only ? (
          <PlanView plan={rule.plan} explanation={rule.explanation} naturalLanguageOnly={rule.natural_language_only} />
        ) : null}
        {canRetry ? (
          <div style={{ marginTop: 6 }}>
            {retryFor === rule.rule_key ? (
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  className="filter"
                  style={{ flex: 1, minWidth: 220 }}
                  placeholder="Optional note for the compiler — e.g. “this should be at RPG level, not account”"
                  value={retryNote}
                  onChange={(e) => setRetryNote(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !retryBusy) retry(rule.rule_key as string);
                    if (e.key === "Escape") setRetryFor(null);
                  }}
                />
                <button className="btn primary" disabled={retryBusy} onClick={() => retry(rule.rule_key as string)}>
                  {retryBusy ? "Compiling…" : "Ask for another plan"}
                </button>
                <button className="btn" disabled={retryBusy} onClick={() => setRetryFor(null)}>
                  Cancel
                </button>
              </div>
            ) : (
              <button
                className="btn"
                onClick={() => {
                  setRetryFor(rule.rule_key as string);
                  setRetryNote("");
                  setRetryError(null);
                }}
              >
                {rule.plan ? "Retry query generation" : "Generate query"}
              </button>
            )}
            {retryError && retryFor === rule.rule_key ? (
              <div style={{ color: "var(--neg, #B3261E)", fontSize: 12.5, marginTop: 4 }}>{retryError}</div>
            ) : null}
          </div>
        ) : null}
        {rule.rule_key && (rule.compile_attempts?.length ?? 0) > 0 ? (
          <details className="tech" style={{ marginTop: 6 }} open={(rule.compile_attempts?.length ?? 0) > 1}>
            <summary>
              {rule.compile_attempts?.length} compile attempt{(rule.compile_attempts?.length ?? 0) === 1 ? "" : "s"}
            </summary>
            <AttemptCompare
              ruleKey={rule.rule_key}
              attempts={rule.compile_attempts ?? []}
              pickedAttemptNo={rule.picked_attempt_no}
              onPicked={refreshRules}
            />
          </details>
        ) : null}
        {citation ? (
          <div className="rule-f">
            <SourceLink>
              {citation.document_name || citation.chunk_id}
              {citation.page_no != null ? ` · p. ${citation.page_no}` : ""}
              {citation.section_path ? ` · ${citation.section_path}` : ""}
            </SourceLink>
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <section>
      <PageHeader
        title="Documents & Rules"
        meta="Upload documents, write rules in plain English, and review the rules the engine runs"
      />
      <div className="grid2">
        <div>
          <div className="card">
            <div className="card-h">
              <div>
                <h2>Documents</h2>
                <p>Six categories — only PLAN and FAQ feed the Rule Extractor; everything is searchable.</p>
              </div>
            </div>
            <div className="card-b">
              <div className="drop">
                <b>Drop Files Here</b>
                <p>PDF, Word, PowerPoint, .txt or .csv · several files at once · tables and page numbers are preserved</p>
                <div style={{ display: "flex", gap: 8, justifyContent: "center", alignItems: "center", marginBottom: 10 }}>
                  <span style={{ fontSize: "12.5px", color: "var(--slate)" }}>Category</span>
                  <select value={docType} onChange={(e) => setDocType(e.target.value as DocumentCategory)}>
                    {DOCUMENT_CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {CATEGORY_LABELS[c]}
                      </option>
                    ))}
                  </select>
                </div>
                <button className="btn primary" disabled={uploading} onClick={() => fileInput.current?.click()}>
                  {uploading ? "Uploading…" : "Browse Files"}
                </button>
                <input ref={fileInput} type="file" multiple hidden onChange={(e) => onFiles(e.target.files)} />
              </div>
              {docActionError ? (
                <div style={{ color: "var(--neg, #B3261E)", fontSize: 12.5, margin: "8px 0" }}>{docActionError}</div>
              ) : null}
              {documents && documents.length ? (
                <ul className="doclist">
                  {documents.map((doc) => {
                    const chip = statusChip(doc.status);
                    const category = (doc.document_category || doc.document_type || "PLAN") as DocumentCategory;
                    return (
                      <li key={doc.document_id}>
                        <div>
                          <b>{doc.document_name}</b>
                          <div className="meta">
                            {[
                              doc.page_count != null ? `${doc.page_count} pages` : null,
                              doc.chunk_count != null ? `${doc.chunk_count} chunks` : null,
                              doc.table_chunk_count != null ? `${doc.table_chunk_count} table chunks` : null,
                              doc.rule_count != null ? `${doc.rule_count} rules` : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </div>
                          {extractionOffer === doc.document_id ? (
                            <div style={{ marginTop: 6, fontSize: 12.5 }}>
                              This category feeds the Rule Extractor — run extraction now?{" "}
                              <button
                                className="btn primary"
                                style={{ padding: "3px 9px" }}
                                disabled={extractBusy}
                                onClick={() => runExtraction(doc.document_id)}
                              >
                                {extractBusy ? "Extracting…" : "Run extraction"}
                              </button>{" "}
                              <button
                                className="btn"
                                style={{ padding: "3px 9px" }}
                                disabled={extractBusy}
                                onClick={() => setExtractionOffer(null)}
                              >
                                Not now
                              </button>
                            </div>
                          ) : null}
                        </div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <select
                            value={DOCUMENT_CATEGORIES.includes(category) ? category : "OTHER"}
                            disabled={categoryBusy === doc.document_id}
                            title={
                              EXTRACTING_CATEGORIES.includes(category)
                                ? "This category feeds the Rule Extractor"
                                : "Indexed and searchable — never produces rules"
                            }
                            onChange={(e) => changeCategory(doc.document_id, e.target.value as DocumentCategory)}
                          >
                            {DOCUMENT_CATEGORIES.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </select>
                          <Chip variant={chip.variant}>{chip.label}</Chip>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState
                  title={documentsError ? "Documents Unavailable" : "No Documents Yet"}
                  message={documentsError ?? "Upload a plan document to begin."}
                />
              )}
            </div>
          </div>
          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-h">
              <div>
                <h2>Write a Rule</h2>
                <p>Plain English, no document — with or without a generated query.</p>
              </div>
            </div>
            <div className="card-b">
              <ManualRuleForm onCreated={refreshRules} />
            </div>
          </div>
        </div>
        <div>
          <div className="card">
            <div className="card-h">
              <div>
                <h2>Rules Awaiting Review</h2>
                <p>Extracted, seeded and hand-written rules — the gaps are shown, never hidden.</p>
              </div>
            </div>
            <div className="card-b">
              {extraction ? <ExtractionSummaryBlock summary={extraction} /> : null}
              {/* Task 4 (Subagent A) — multi-select delete, deactivate/
                  reactivate, filters. Mounted as-is; renders nothing until
                  the implementation lands. */}
              <RuleListManager />
              {rules && rules.length ? (
                rules.map(ruleCard)
              ) : (
                <EmptyState
                  title={rulesError ? "Rules Unavailable" : "No Rules Awaiting Review"}
                  message={rulesError ?? "Extracted draft rules will appear here for approval."}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
