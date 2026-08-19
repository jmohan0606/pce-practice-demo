"use client";

/** Documents & Rules — Round 3 Task 12a: the redesign, not fixes.
 *
 * The old page crammed upload + documents + rules + write-a-rule into one
 * congested two-column layout with a horizontal scrollbar (the always-open
 * compiled query was the cause). It is now FOUR TABS, each with the full page
 * width:
 *
 *   Documents   — upload + category + the paginated document list (built for
 *                 dozens of documents, not four)
 *   Rules       — the full rules list (RuleListManager): paginated, filterable
 *                 by status / provenance / scope / severity, compiled query
 *                 collapsed, attempts opened on click
 *   Exceptions  — the served version's rules with independent driver /
 *                 exception toggles and per-rule materiality config
 *   Write a Rule — ManualRuleForm with room to breathe
 *
 * Nothing overflows: rule line items wrap within the component width and no
 * tab produces a horizontal scrollbar.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  type DocumentInfo,
  type RuleDetail,
  getDocuments,
  getRulesDetailed,
  uploadDocuments,
} from "@/lib/api";
import {
  type BatchApproveResult,
  DOCUMENT_CATEGORIES,
  type DocumentCategory,
  EXTRACTING_CATEGORIES,
  RulesApiError,
  batchApproveDocument,
  setDocumentCategory,
} from "@/lib/rulesApi";
import Chip, { type ChipVariant } from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { Pager, usePager } from "@/components/Pager";
import ExceptionsTab from "@/components/rules/ExceptionsTab";
import ExtractionProgress from "@/components/rules/ExtractionProgress";
import ManualRuleForm from "@/components/rules/ManualRuleForm";
import RuleListManager, { type RulesPreset } from "@/components/rules/RuleListManager";

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

const TABS = [
  { id: "documents", label: "Documents" },
  { id: "rules", label: "Rules" },
  { id: "exceptions", label: "Exceptions" },
  { id: "write", label: "Write a Rule" },
] as const;
type TabId = (typeof TABS)[number]["id"];

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

export default function DocumentsPage() {
  const [tab, setTab] = useState<TabId>("documents");
  // Round 8 — ?tab=exceptions|rules|write deep link (the dashboard's empty
  // states link straight to the Exceptions tab). Read once on mount;
  // window.location avoids the useSearchParams Suspense requirement.
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted && TABS.some((t) => t.id === wanted)) setTab(wanted as TabId);
  }, []);
  const [documents, setDocuments] = useState<DocRow[] | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  // 3.1: category chosen at upload, defaulting PLAN. Only PLAN and FAQ feed
  // the Rule Extractor; every category is chunked, embedded and searchable.
  const [docType, setDocType] = useState<DocumentCategory>("PLAN");
  const [categoryBusy, setCategoryBusy] = useState<string | null>(null);
  // Round 7 task 1: uploads AND reclassifications can each raise an offer, so
  // several documents may be offering extraction at once.
  const [extractionOffer, setExtractionOffer] = useState<string[]>([]);
  const [extractingDoc, setExtractingDoc] = useState<string | null>(null);
  // Round 7 task 2 — Max Rule Extraction Limit: the extractor ranks provisions
  // by significance across the whole document and returns the top N (never a
  // truncation of whatever came first).
  const [extractLimit, setExtractLimit] = useState<number>(10);
  const [docActionError, setDocActionError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  // Round 5 task 13 — the journey across the tabs
  const [drafts, setDrafts] = useState<RuleDetail[]>([]);
  const [rulesPreset, setRulesPreset] = useState<RulesPreset | null>(null);
  const [batchFor, setBatchFor] = useState<DocRow | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchResult, setBatchResult] = useState<BatchApproveResult | null>(null);

  const refreshDrafts = useCallback(() => {
    getRulesDetailed("drafts")
      .then((res) => setDrafts(res.rules ?? []))
      .catch(() => setDrafts([]));
  }, []);

  useEffect(() => {
    refreshDrafts();
  }, [refreshDrafts]);

  // 13.2 — per-document draft-pool counts (the handoff into the Rules tab)
  const draftsByDoc = useMemo(() => {
    const grouped: Record<string, RuleDetail[]> = {};
    for (const r of drafts) {
      if (!r.document_id) continue;
      (grouped[r.document_id] ??= []).push(r);
    }
    return grouped;
  }, [drafts]);

  // switch to the Rules tab with preset filters (13.2 → 13.3); the token
  // makes the same link clickable twice
  const openRules = useCallback((preset: Omit<RulesPreset, "token">) => {
    setRulesPreset({ ...preset, token: Date.now() });
    setTab("rules");
  }, []);

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
            ? "The document service is not reachable."
            : String(e?.message || e),
        );
      });
  }, []);

  useEffect(() => {
    refreshDocuments();
  }, [refreshDocuments]);

  // Task 12a — the document list is designed for dozens of documents
  const docPager = usePager(documents ?? []);

  const onFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || !files.length) return;
      setUploading(true);
      try {
        // lib/api's uploadDocuments signature predates the six-category
        // contract; the backend accepts all six (validated server-side).
        const res = await uploadDocuments(Array.from(files), docType as "PLAN" | "GUIDANCE");
        // Round 7 task 1: uploading as PLAN/FAQ offers extraction IMMEDIATELY —
        // no second selection on the row dropdown.
        const offered = (res.documents ?? [])
          .filter((d) => d.extraction_offered)
          .map((d) => d.document_id);
        if (offered.length) setExtractionOffer((cur) => [...new Set([...cur, ...offered])]);
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
      setExtractionOffer((cur) => cur.filter((id) => id !== documentId));
      try {
        const res = await setDocumentCategory(documentId, category);
        // 3.1: changing to PLAN or FAQ offers to run extraction — offered,
        // never auto-run.
        if (res.extraction_offered) setExtractionOffer((cur) => [...new Set([...cur, documentId])]);
        refreshDocuments();
      } catch (e) {
        setDocActionError(
          e instanceof RulesApiError
            ? e.status === 0 || e.status === 404
              ? "The document category service is not reachable."
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
      setExtractingDoc(documentId);
      setDocActionError(null);
      try {
        const response = await fetch(
          `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/extract-rules?limit=${extractLimit}`,
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
        setExtractionOffer((cur) => cur.filter((id) => id !== documentId));
        refreshDocuments();
        refreshDrafts();
      } catch (e) {
        setDocActionError(String((e as Error)?.message || e));
      } finally {
        setExtractingDoc(null);
      }
    },
    [refreshDocuments, refreshDrafts, extractLimit],
  );

  // 13.4 — batch approval: list first, approve on confirm, one version minted
  const runBatchApprove = useCallback(async () => {
    if (!batchFor) return;
    setBatchBusy(true);
    setBatchError(null);
    try {
      const result = await batchApproveDocument(batchFor.document_id);
      setBatchResult(result);
      setBatchFor(null);
      refreshDrafts();
      refreshDocuments();
    } catch (e) {
      setBatchError(
        e instanceof RulesApiError ? e.message : String((e as Error)?.message || e),
      );
    } finally {
      setBatchBusy(false);
    }
  }, [batchFor, refreshDrafts, refreshDocuments]);

  const documentsTab = (
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
          <div style={{ display: "flex", gap: 8, justifyContent: "center", alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
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
        {/* 13.5 — close the loop: what changed and where it went */}
        {batchResult ? (
          <div className="note" style={{ border: "1px solid var(--rule)", borderRadius: 5, margin: "8px 0" }}>
            <b>
              Published rule set v{batchResult.version?.version_no ?? "?"} —{" "}
              {batchResult.approved_count} rule{batchResult.approved_count === 1 ? "" : "s"} from{" "}
              {batchResult.document_name || batchResult.document_id}.
            </b>{" "}
            <a href="/rules">View in Rule Versions</a>
            {" · "}
            <button
              type="button"
              onClick={() => {
                window.location.href = "/";
              }}
              style={{ background: "none", border: "none", padding: 0, font: "inherit", color: "var(--brand, #0B5FFF)", textDecoration: "underline", cursor: "pointer" }}
              title="Opens the Dashboard's AI Insights section — generation only runs when you press Generate there; it is never triggered automatically"
            >
              Regenerate insights (on the Dashboard)
            </button>
            {batchResult.failures.length ? (
              <div style={{ marginTop: 6, fontSize: 12.5 }}>
                <b>Not approved:</b>
                {batchResult.failures.map((f) => (
                  <div key={f.rule_key} className="eg">
                    <b>{f.rule_code || f.rule_key}</b> — {f.reason}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {documents && documents.length ? (
          <>
            <ul className="doclist">
              {docPager.rows.map((doc) => {
                const chip = statusChip(doc.status);
                const category = (doc.document_category || doc.document_type || "PLAN") as DocumentCategory;
                const docDrafts = draftsByDoc[doc.document_id] ?? [];
                const compiledCount = docDrafts.filter((r) => r.status === "COMPILED").length;
                const needsInputCount = docDrafts.filter((r) => r.status === "NEEDS_INPUT").length;
                const needsDataCount = docDrafts.filter((r) => r.status === "NEEDS_DATA").length;
                const countLink = (label: string, status: string | undefined) => (
                  <button
                    type="button"
                    onClick={() => openRules({ documentId: doc.document_id, status })}
                    title="Open the Rules tab filtered to this document and status"
                    style={{
                      background: "none",
                      border: "none",
                      padding: 0,
                      font: "inherit",
                      color: "var(--brand, #0B5FFF)",
                      textDecoration: "underline",
                      cursor: "pointer",
                    }}
                  >
                    {label}
                  </button>
                );
                return (
                  <li key={doc.document_id}>
                    <div style={{ minWidth: 0 }}>
                      <b style={{ overflowWrap: "anywhere" }}>{doc.document_name}</b>
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
                      {/* 13.2 — extraction counts are the handoff: each count
                          links into the Rules tab pre-filtered to this
                          document AND that status */}
                      {docDrafts.length ? (
                        <div style={{ marginTop: 4, fontSize: 12.5, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                          {countLink(`${docDrafts.length} extracted`, undefined)}
                          <span>·</span>
                          {countLink(`${compiledCount} compiled`, "COMPILED")}
                          <span>·</span>
                          {countLink(`${needsInputCount} need a value`, "NEEDS_INPUT")}
                          <span>·</span>
                          {countLink(`${needsDataCount} need data we don’t have`, "NEEDS_DATA")}
                          {compiledCount > 0 ? (
                            <button
                              className="btn"
                              style={{ padding: "2px 8px", marginLeft: 6 }}
                              disabled={batchBusy}
                              onClick={() => {
                                setBatchError(null);
                                setBatchResult(null);
                                setBatchFor(doc);
                              }}
                            >
                              Approve all compiled from this document ({compiledCount})
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                      {/* 13.1 — live stage progress from the job record; an
                          INTERRUPTED job offers an explicit Resume */}
                      <ExtractionProgress
                        documentId={doc.document_id}
                        extracting={extractingDoc === doc.document_id}
                        onFinished={() => {
                          refreshDocuments();
                          refreshDrafts();
                        }}
                      />
                      {extractionOffer.includes(doc.document_id) ? (
                        <div style={{ marginTop: 6, fontSize: 12.5, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <span>This category feeds the Rule Extractor — run extraction now?</span>
                          <label style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
                            <span
                              title="The extractor ranks provisions by significance across the whole document and returns the top N — a ranking, never a truncation"
                              style={{ color: "var(--slate)" }}
                            >
                              Max Rule Extraction Limit
                            </span>
                            <select
                              value={extractLimit}
                              disabled={extractingDoc !== null}
                              onChange={(e) => setExtractLimit(Number(e.target.value))}
                            >
                              {[5, 10, 20].map((n) => (
                                <option key={n} value={n}>
                                  {n}
                                </option>
                              ))}
                            </select>
                          </label>{" "}
                          <button
                            className="btn primary"
                            style={{ padding: "3px 9px" }}
                            disabled={extractingDoc !== null}
                            onClick={() => runExtraction(doc.document_id)}
                          >
                            {extractingDoc === doc.document_id ? "Extracting…" : "Run extraction"}
                          </button>{" "}
                          <button
                            className="btn"
                            style={{ padding: "3px 9px" }}
                            disabled={extractingDoc !== null}
                            onClick={() => setExtractionOffer((cur) => cur.filter((id) => id !== doc.document_id))}
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
            <Pager {...docPager} noun="documents" />
          </>
        ) : (
          <EmptyState
            title={documentsError ? "Documents Unavailable" : "No Documents Yet"}
            message={documentsError ?? "Upload a plan document to begin."}
          />
        )}
      </div>
    </div>
  );

  return (
    <section>
      <PageHeader
        title="Documents & Rules"
        meta="Upload documents, review and configure the rules the engine runs, and write rules in plain English"
      />

      {/* Task 12a — the four jobs of this page, one tab each, full page width */}
      <div className="pivot" role="tablist" aria-label="Documents and rules sections" style={{ display: "inline-flex", marginBottom: 16 }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "documents" ? documentsTab : null}

      {/* 13.4 — batch approval confirm: LISTS every rule it is about to
          approve, never a blind bulk action. Only COMPILED rules are listed
          (NEEDS_INPUT / NEEDS_DATA are ineligible; the API refuses them too). */}
      <div className={`scrim${batchFor ? " on" : ""}`} onClick={() => (batchBusy ? null : setBatchFor(null))}></div>
      <div
        className={`modal narrow${batchFor ? " on" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Approve all compiled rules from this document"
      >
        <div className="m-head">
          Approve {batchFor ? (draftsByDoc[batchFor.document_id] ?? []).filter((r) => r.status === "COMPILED").length : 0}{" "}
          Compiled Rule
          {batchFor && (draftsByDoc[batchFor.document_id] ?? []).filter((r) => r.status === "COMPILED").length === 1 ? "" : "s"}
          ?
        </div>
        <div className="m-body">
          <p style={{ margin: "0 0 10px", fontSize: 13, color: "var(--slate)" }}>
            These compiled rules from <b>{batchFor?.document_name}</b> will be approved and
            published together as ONE new rule-set version. Rules still needing a value or data
            are not included — they cannot run.
          </p>
          {batchFor
            ? (draftsByDoc[batchFor.document_id] ?? [])
                .filter((r) => r.status === "COMPILED")
                .map((r) => (
                  <div key={r.rule_key || r.rule_code} className="eg" style={{ marginBottom: 6 }}>
                    <b>{r.rule_code}</b> — {r.rule_name || "unnamed"}
                  </div>
                ))
            : null}
          {batchError ? (
            <div className="note" style={{ border: "1px solid var(--neg-br)", borderRadius: 5, marginTop: 8 }}>
              {batchError}
            </div>
          ) : null}
        </div>
        <div className="m-foot">
          <button className="btn" disabled={batchBusy} onClick={() => setBatchFor(null)}>
            Cancel
          </button>
          <button className="btn primary" disabled={batchBusy} onClick={runBatchApprove}>
            {batchBusy ? "Approving…" : "Approve and publish"}
          </button>
        </div>
      </div>

      {tab === "rules" ? (
        <div className="card">
          <div className="card-h">
            <div>
              <h2>Rules</h2>
              <p>
                Every rule — extracted, seeded and hand-written — at full page width. Filter by
                status, provenance, scope or severity; the compiled query and compile attempts
                open on click.
              </p>
            </div>
          </div>
          <div className="card-b">
            <RuleListManager preset={rulesPreset} />
          </div>
        </div>
      ) : null}

      {tab === "exceptions" ? (
        <div className="card">
          <div className="card-h">
            <div>
              <h2>Exceptions</h2>
              <p>
                Which rules explain revenue, which flag advisors, and what counts as material —
                per rule, on the served version.
              </p>
            </div>
          </div>
          <div className="card-b">
            <ExceptionsTab />
          </div>
        </div>
      ) : null}

      {tab === "write" ? (
        <div className="card" style={{ maxWidth: 760 }}>
          <div className="card-h">
            <div>
              <h2>Write a Rule</h2>
              <p>Plain English, no document — with or without a generated query.</p>
            </div>
          </div>
          <div className="card-b">
            <ManualRuleForm />
          </div>
        </div>
      ) : null}
    </section>
  );
}
