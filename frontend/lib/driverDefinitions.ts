/** Round F 5.1 — the ONE place driver-tag definitions live in the frontend.
 *
 * A driver chip's tooltip prefers the statement of the rule the finding
 * matched (served on `finding.rule_citation.statement`); this table is the
 * fallback for findings with no rule. Do not scatter per-component copies.
 */
const DRIVER_DEFINITIONS: Record<string, string> = {
  "New Billing":
    "An account that held a balance in the prior month but produced no credited revenue, " +
    "and produced credited revenue this month. Distinct from a new account, which did not " +
    "exist before.",
  "New Accounts":
    "An account that did not exist in the prior month and produced credited revenue this month.",
  "Lost Accounts":
    "An account that produced credited revenue in the prior month and produces none this month — closed or zeroed.",
  Transfers:
    "An account that moved into or out of this advisor's book from or to another advisor.",
  "Fee Rate":
    "The effective fee rate on an account or product changed — the same balance billed at a different rate.",
  Market:
    "Market movement changed billable balances without client money moving in or out.",
  Flows:
    "Client money moved in or out of existing accounts, changing the billable balance.",
  "One-Time":
    "A non-recurring item — a one-off fee, adjustment, or correction not expected to repeat next month.",
  Inherited:
    "Revenue on accounts inherited from another advisor.",
  Referrals:
    "Revenue connected to a referral arrangement.",
  "Period Length":
    "The billing periods being compared differ in length, changing the amount billed.",
  Calendar:
    "A calendar effect — day counts, billing dates, or month boundaries — changed the amount billed.",
  Mix:
    "The blend of products or accounts shifted toward higher- or lower-fee holdings.",
  Other:
    "A movement that does not fit a standard driver category — see the finding's evidence rows.",
};

/** The tooltip definition for a driver tag, or undefined when we have none. */
export function driverDefinition(tag: string | null | undefined): string | undefined {
  return tag ? DRIVER_DEFINITIONS[tag] : undefined;
}

export default DRIVER_DEFINITIONS;
