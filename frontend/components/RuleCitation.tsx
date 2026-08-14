import Link from "next/link";
import type { RuleCitation as Citation } from "@/lib/api";

/** Round A2B 1.5 — the rule-and-source thread under an insight, driver or
 * exception. Rule name links to /rules?rule=<key>; the document citation
 * renders where one exists. A tech-written rule says so explicitly rather
 * than showing nothing.
 */
export default function RuleCitationLine({
  ruleKey,
  ruleName,
  citation,
  provenance,
}: {
  ruleKey: string;
  ruleName?: string | null;
  /** First document citation, if the rule has one. */
  citation?: Citation | null;
  /** Rule provenance — TECH_TEAM_WRITTEN / OPERATOR_SPECIFIED rules have no document source. */
  provenance?: string | null;
}) {
  const docPart = citation?.document_name ? (
    <a className="src" href={`/documents?doc=${encodeURIComponent(citation.document_name)}`}>
      {citation.document_name}
      {citation.page_no != null ? ` · p. ${citation.page_no}` : ""}
      {citation.section_path ? ` · ${citation.section_path}` : ""}
    </a>
  ) : (
    <span className="techsrc">
      {provenance === "DOCUMENT_DERIVED" ? "No document citation" : "Tech team written — no document source"}
    </span>
  );
  return (
    <span className="rulecite">
      <Link className="rulelink" href={`/rules?rule=${encodeURIComponent(ruleKey)}`}>
        Rule: {ruleName || ruleKey}
      </Link>
      {" · "}
      {docPart}
    </span>
  );
}
