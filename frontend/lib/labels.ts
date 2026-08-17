/** Round 3 task 6.5/6.6 — ONE naming surface for every label the UI renders.
 *
 * No underscores, no raw field names, proper capitalisation, booleans as
 * Yes / No. Anywhere a column header or field label appears it goes through
 * `labelize`; anywhere a boolean renders it goes through `yesNo`.
 */

/** Known fields get their proper business name (a raw-name split would be
 * wrong or clumsy for these). Everything else falls back to the generic
 * splitter below. */
export const FIELD_LABELS: Record<string, string> = {
  key: "Account",
  acct_key: "Account",
  value: "Value",
  reason_cd: "Reason Code",
  non_credited_amt: "Non-Credited Amount",
  credited_amt: "Credited Revenue",
  prior_credited_amt: "Prior-Month Revenue",
  prior_balance: "Prior Balance",
  prior_end_balance: "Prior End Balance",
  end_balance: "End Balance",
  txn_count: "Transactions",
  txn_id: "Transaction",
  trade_dt: "Trade Date",
  trade_description: "Trade Description",
  advisor_sid: "Advisor",
  advisor_name: "Advisor",
  from_advisor_sid: "From Advisor",
  to_advisor_sid: "To Advisor",
  transfer_ts: "Transferred",
  month_id: "Month",
  group_id: "Product Group",
  group_name: "Product Group",
  product_id: "Product",
  rpg_id: "Pricing Group",
  eci_id: "Household",
  is_zero_balance: "Zero Balance",
  is_new_to_product: "New To Product",
  is_managed: "Managed",
  from_amt: "From",
  to_amt: "To",
  change_amt: "Change",
  change_pct: "Change %",
  share_pct: "% Share",
  impact_amt: "Impact",
  standard_bps: "Standard (bps)",
  client_bps: "Client (bps)",
  reduction_pct: "Reduction %",
  grid_reduction: "Grid Reduction",
  account_open_dt: "Opened",
  first_month_revenue: "First-Month Revenue",
  account_count: "Accounts",
  advisor_count: "Advisors",
  trade_count: "Trades",
  opportunity_count: "Opportunities",
  actual_assets: "Actual Assets",
  forecast_amount: "Amount",
  amount: "Amount",
  days_to_close: "Days To Close",
  stage_group: "Stage",
  net_flows: "Net Flows",
  inflows: "Inflows",
  outflows: "Outflows",
  credited_flows: "Credited Flows",
  flow_product_cd: "Flow Product",
  rate_pct: "Rate",
  cohort_median_pct: "Cohort Median",
  affected: "Affected",
  denominator: "Denominator",
  aum: "AUM",
  total_balance: "Total Balance",
};

const WORD_FIXES: Record<string, string> = {
  amt: "Amount",
  cd: "Code",
  dt: "Date",
  pct: "%",
  sid: "SID",
  id: "ID",
  aum: "AUM",
  ncf: "NCF",
  nnm: "NNM",
  eci: "Household",
  rpg: "Pricing Group",
  txn: "Transaction",
  num: "Number",
  ts: "Time",
  bps: "bps",
};

/** `non_credited_amt` → "Non Credited Amount"; known fields get their proper
 * business label first. Never returns an underscore. */
export function labelize(field: string): string {
  if (!field) return "";
  const known = FIELD_LABELS[field] ?? FIELD_LABELS[field.toLowerCase()];
  if (known) return known;
  return field
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => {
      const fix = WORD_FIXES[w.toLowerCase()];
      if (fix) return fix;
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
    })
    .join(" ")
    .replace(/^Is /, "");
}

/** Round 3 task 6.6 — booleans render Yes / No, never true / false. */
export function yesNo(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const truthy =
    value === true ||
    String(value).trim().toLowerCase() === "true" ||
    String(value).trim() === "1" ||
    String(value).trim().toLowerCase() === "yes";
  return truthy ? "Yes" : "No";
}

/** Is this value boolean-ish (so a table cell knows to render Yes/No)? */
export function isBooleanish(value: unknown): boolean {
  if (typeof value === "boolean") return true;
  const s = String(value).trim().toLowerCase();
  return s === "true" || s === "false";
}
