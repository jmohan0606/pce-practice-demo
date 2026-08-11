"use client";

import { useEffect, useState } from "react";
import { ApiError, type RuleVersion, getRuleVersions } from "@/lib/api";
import Chip from "@/components/Chip";
import EmptyState from "@/components/EmptyState";
import PageHeader from "@/components/PageHeader";

/** Rule Set Versions — no filters on this page. Versions are superseded, never
 * deleted. Built against the B3 endpoint shapes (landing in parallel). */
export default function RuleVersionsPage() {
  const [versions, setVersions] = useState<RuleVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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

  return (
    <section>
      <PageHeader title="Rule Set Versions" meta="Every insight records the version that produced it" />
      <div className="card">
        <div className="card-h">
          <div>
            <h2>Rule Set Versions</h2>
            <p>Each insight records the version that produced it. Versions are superseded, never deleted.</p>
          </div>
        </div>
        <div className="card-b">
          {versions && versions.length ? (
            <ul className="vers">
              {versions.map((v) => {
                const status = (v.status || "").toUpperCase();
                const current = status === "PUBLISHED";
                return (
                  <li key={v.version_id ?? v.version_no} className={current ? "cur" : undefined}>
                    <div>
                      <b>
                        v{v.version_no}
                        {v.published_at ? ` · Published ${v.published_at}` : v.created_at ? ` · ${v.created_at}` : ""}
                      </b>
                      <div className="meta">
                        {[
                          v.rule_count != null ? `${v.rule_count} rules` : null,
                          v.document_count != null ? `${v.document_count} source documents` : null,
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
                      {v.insight_count != null ? (
                        <div className="meta">{v.insight_count} insights</div>
                      ) : null}
                    </div>
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
