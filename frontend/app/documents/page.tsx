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

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type DocumentInfo,
  getDocuments,
  uploadDocuments,
} from "@/lib/api";
import {
  DOCUMENT_CATEGORIES,
  type DocumentCategory,
  EXTRACTING_CATEGORIES,
  RulesApiError,
  setDocumentCategory,
} from "@/lib/rulesApi";
import Chip, { type ChipVariant } from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import { Pager, usePager } from "@/components/Pager";
import ExceptionsTab from "@/components/rules/ExceptionsTab";
import ManualRuleForm from "@/components/rules/ManualRuleForm";
import RuleListManager from "@/components/rules/RuleListManager";

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
  const [documents, setDocuments] = useState<DocRow[] | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  // 3.1: category chosen at upload, defaulting PLAN. Only PLAN and FAQ feed
  // the Rule Extractor; every category is chunked, embedded and searchable.
  const [docType, setDocType] = useState<DocumentCategory>("PLAN");
  const [categoryBusy, setCategoryBusy] = useState<string | null>(null);
  const [extractionOffer, setExtractionOffer] = useState<string | null>(null);
  const [extractBusy, setExtractBusy] = useState(false);
  const [docActionError, setDocActionError] = useState<string | null>(null);
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
      } catch (e) {
        setDocActionError(String((e as Error)?.message || e));
      } finally {
        setExtractBusy(false);
      }
    },
    [refreshDocuments],
  );

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
        {documents && documents.length ? (
          <>
            <ul className="doclist">
              {docPager.rows.map((doc) => {
                const chip = statusChip(doc.status);
                const category = (doc.document_category || doc.document_type || "PLAN") as DocumentCategory;
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
            <RuleListManager />
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
