#!/usr/bin/env python3
"""Round 4 task 8 — generate insights for the TOP/BOTTOM advisors of a product.

    python3 scripts/generate_topbottom_insights.py --from 202604 --to 202605
    python3 scripts/generate_topbottom_insights.py --from 202604 --to 202605 \\
        --product twhs_equities --limit 5

Selection uses the SAME ranking as the dashboard's Top/Bottom modal
(GET /api/dashboard/product/{group_id}/ranking → product_advisor_ranking),
so the advisors generated for are exactly the ones the client sees ranked —
no list to maintain, no drift. Fewer than --limit advisors in the product
returns however many exist. The selection is printed BEFORE the cost prompt.

# Valid --product values — generated from app/revenue/products.py by:
#   python3 -c "from app.revenue.products import PRODUCT_GROUPS;
#               [print(g.group_id) for g in PRODUCT_GROUPS]"
# (runtime validation imports products.py directly, so this block can never
#  silently drift — an invalid value prints the live list and exits)
#
#   managed_accounts                 Managed Accounts  (RECURRING)
#   managed_uma                      Managed – Unified Managed Accounts  (RECURRING)
#   trails_mutual_funds              Trails – Mutual Funds  (RECURRING)
#   trails_life_annuities            Trails – Life & Annuities  (RECURRING)
#   cash_mgmt_mmkt                   Cash Management – Money Market Funds  (RECURRING)
#   cash_mgmt_prdp                   Cash Management – Premium Deposits  (RECURRING)
#   referrals_sit_partnership        Referrals & Revenue Share – Situational Partnership  (RECURRING)
#   plans_529                        529 Plans  (RECURRING)
#   donor_advised_funds              Donor Advised Funds  (RECURRING)
#   twhs_structured                  TWHS – Structured Products  (NON_RECURRING)
#   twhs_equities                    TWHS – Equities  (NON_RECURRING)
#   twhs_options                     TWHS – Options  (NON_RECURRING)
#   twhs_mutual_funds                TWHS – Mutual Funds  (NON_RECURRING)
#   twhs_fi_corporate                TWHS – Fixed Income – Corporate Bonds  (NON_RECURRING)
#   twhs_fi_municipal                TWHS – Fixed Income – Municipal Bonds  (NON_RECURRING)
#   twhs_fi_government               TWHS – Fixed Income – Government Bonds  (NON_RECURRING)
#   twhs_fi_other                    TWHS – Fixed Income – Other  (NON_RECURRING)
#   twhs_cash_mgmt_cds               TWHS – Cash Management – Brokered CDs  (NON_RECURRING)
#   life_annuities                   Life & Annuities  (NON_RECURRING)
#   alternative_investments          Alternative Investments  (NON_RECURRING)
#   defined_contribution_advisory    Defined Contribution Advisory  (NON_RECURRING)
#   lending_sbl                      Lending – Security Based Lending  (NON_RECURRING)
#   lending_margin                   Lending – Margin  (NON_RECURRING)
#   referrals_everyday_401k          Referrals & Revenue Share – Everyday 401K  (NON_RECURRING)
#   referrals_private_bank           Referrals & Revenue Share – Private Bank Referral  (NON_RECURRING)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _generate_insights_common import (  # noqa: E402
    GenError,
    add_common_args,
    api_get,
    check_prerequisites,
    confirm_or_exit,
    cost_projection,
    run_targets,
)


def _valid_products() -> list[str]:
    """Always the LIVE list — imported from app/revenue/products.py, so a
    group added in a later round (referrals_private_bank was) is never
    missing here."""
    from app.revenue.products import PRODUCT_GROUPS

    return [g.group_id for g in PRODUCT_GROUPS]


def _money(v: float) -> str:
    return f"-${abs(v):,.0f}" if v < 0 else f"+${v:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_month", required=True)
    parser.add_argument("--to", dest="to_month", required=True)
    parser.add_argument("--product", default="managed_accounts",
                        help="product group id (default managed_accounts)")
    parser.add_argument("--limit", type=int, default=10,
                        help="advisors per side (default 10 → up to 20 runs)")
    add_common_args(parser)
    args = parser.parse_args()

    valid = _valid_products()
    if args.product not in valid:
        print(f"ERROR: unknown --product '{args.product}'. Valid products:")
        for gid in valid:
            print(f"  {gid}")
        return 2

    try:
        prereqs = check_prerequisites(require_real=args.require_real)
        version_id = args.version_id or prereqs["published_version_id"]

        ranking = api_get(f"/api/dashboard/product/{args.product}/ranking"
                          f"?from={args.from_month}&to={args.to_month}"
                          f"&limit={args.limit}")
        top = ranking.get("top") or []
        bottom = ranking.get("bottom") or []
        # dedupe (an advisor can be on both sides in a small product)
        seen: dict[str, dict] = {}
        for row in [*top, *bottom]:
            seen.setdefault(row["advisor_sid"], row)
        selected = list(seen.values())
        if not selected:
            raise GenError(f"no advisors have revenue in '{args.product}' for "
                           f"{args.from_month} -> {args.to_month} — nothing to generate")

        # Task 8 — report the selection BEFORE generating, so the operator
        # sees who will be paid for.
        print(f"top/bottom {args.limit} advisors in {args.product}, "
              f"{args.from_month} -> {args.to_month}")
        print("  TOP     " + "   ".join(
            f"{r['advisor_sid']}  {_money(r['change_amt'])}" for r in top) if top else "  TOP     (none)")
        print("  BOTTOM  " + "   ".join(
            f"{r['advisor_sid']}  {_money(r['change_amt'])}" for r in bottom) if bottom else "  BOTTOM  (none)")
        product_total = ranking.get("advisor_count")
        if len(selected) < 2 * args.limit:
            print(f"  {len(selected)} advisors selected (product has "
                  f"{product_total}, fewer than 2 x {args.limit})")
        else:
            print(f"  {len(selected)} advisors selected")

        targets = [{"key": f"advisor|{r['advisor_sid']}|{args.from_month}|"
                           f"{args.to_month}|{version_id}",
                    "label": f"{r['advisor_sid']} ({r.get('advisor_name') or '?'})",
                    "advisor": r["advisor_sid"],
                    "from": args.from_month, "to": args.to_month}
                   for r in selected]
        confirm_or_exit(cost_projection(len(targets)), args.yes)
        return run_targets(f"topbottom_{args.product}", targets, args, version_id)
    except GenError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
