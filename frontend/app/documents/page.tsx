"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type DocumentInfo,
  type Rule,
  getDocuments,
  getRules,
  uploadDocuments,
} from "@/lib/api";
import Chip, { type ChipVariant } from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";
import SourceLink from "@/components/SourceLink";

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

function ruleCard(rule: Rule) {
  const status = (rule.status || "DRAFT").toUpperCase();
  const cls = status === "NEEDS_INPUT" ? "needs" : "draft";
  const chip =
    status === "NEEDS_INPUT" ? (
      <Chip variant="tag">Needs Input</Chip>
    ) : (
      <Chip variant="derived">Draft</Chip>
    );
  const citation = rule.citations?.[0];
  return (
    <div className={`rule ${cls}`} key={rule.rule_code}>
      <div className="rule-h">
        <div className="rule-t">{rule.rule_name || rule.rule_code}</div>
        {chip}
      </div>
      {rule.plain_description ? <div className="rule-d">{rule.plain_description}</div> : null}
      {rule.worked_example ? (
        <div className="eg">
          Example — <b>{rule.worked_example}</b>
        </div>
      ) : null}
      {rule.unclear_notes ? <div className="eg">{rule.unclear_notes}</div> : null}
      {rule.population || rule.compute || rule.trigger || rule.attribute ? (
        <details className="tech">
          <summary>Technical Detail</summary>
          <pre>
            {[
              rule.population ? `population  ${rule.population}` : null,
              rule.compute ? `compute     ${rule.compute}` : null,
              rule.trigger ? `trigger     ${rule.trigger}` : null,
              rule.attribute ? `attribute   ${rule.attribute}` : null,
            ]
              .filter(Boolean)
              .join("\n")}
          </pre>
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
}

/** Documents & Rules — no filters on this page. B2/B3 endpoints are built in
 * parallel; a 404 renders as a graceful pending state, never a crash. */
export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  // 5.2: PLAN documents go to the Rule Extractor; GUIDANCE is chunked +
  // embedded for search only. Chosen at upload, defaulting to PLAN.
  const [docType, setDocType] = useState<"PLAN" | "GUIDANCE">("PLAN");
  const fileInput = useRef<HTMLInputElement>(null);

  const refreshDocuments = useCallback(() => {
    getDocuments()
      .then((res) => {
        setDocuments(res.documents ?? []);
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

  useEffect(() => {
    refreshDocuments();
    getRules("latest")
      .then((res) => {
        setRules((res.rules ?? []).filter((r) => (r.status || "").toUpperCase() !== "PUBLISHED"));
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
  }, [refreshDocuments]);

  const onFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || !files.length) return;
      setUploading(true);
      try {
        await uploadDocuments(Array.from(files), docType);
        refreshDocuments();
      } catch (e) {
        setDocumentsError(String((e as Error)?.message || e));
      } finally {
        setUploading(false);
      }
    },
    [refreshDocuments, docType],
  );

  return (
    <section>
      <PageHeader
        title="Documents & Rules"
        meta="Upload plan documents, then review the rules read from them"
      />
      <div className="grid2">
        <div>
          <div className="card">
            <div className="card-h">
              <div>
                <h2>Documents</h2>
                <p>Plan documents the rules are read from.</p>
              </div>
            </div>
            <div className="card-b">
              <div className="drop">
                <b>Drop Files Here</b>
                <p>PDF, Word or PowerPoint · several files at once · tables and page numbers are preserved</p>
                <div style={{ display: "flex", gap: 8, justifyContent: "center", alignItems: "center", marginBottom: 10 }}>
                  <span style={{ fontSize: "12.5px", color: "var(--slate)" }}>Document type</span>
                  <select value={docType} onChange={(e) => setDocType(e.target.value as "PLAN" | "GUIDANCE")}>
                    <option value="PLAN">PLAN — rules are extracted</option>
                    <option value="GUIDANCE">GUIDANCE — search only</option>
                  </select>
                </div>
                <button
                  className="btn primary"
                  disabled={uploading}
                  onClick={() => fileInput.current?.click()}
                >
                  {uploading ? "Uploading…" : "Browse Files"}
                </button>
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  hidden
                  onChange={(e) => onFiles(e.target.files)}
                />
              </div>
              {documents && documents.length ? (
                <ul className="doclist">
                  {documents.map((doc) => {
                    const chip = statusChip(doc.status);
                    return (
                      <li key={doc.document_id}>
                        <div>
                          <b>{doc.document_name}</b>
                          <div className="meta">
                            {[
                              doc.page_count != null ? `${doc.page_count} pages` : null,
                              doc.chunk_count != null ? `${doc.chunk_count} chunks` : null,
                              doc.table_chunk_count != null
                                ? `${doc.table_chunk_count} table chunks`
                                : null,
                              doc.rule_count != null ? `${doc.rule_count} rules` : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </div>
                        </div>
                        <Chip variant={chip.variant}>{chip.label}</Chip>
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
        </div>
        <div>
          <div className="card">
            <div className="card-h">
              <div>
                <h2>Rules Awaiting Review</h2>
                <p>Draft rules read from uploaded documents.</p>
              </div>
            </div>
            <div className="card-b">
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
