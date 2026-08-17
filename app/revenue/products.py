"""Product model: 25 display groups + revenue classes (SCHEMA_SPEC §1 V3/V4, §4).

Aggregation group and revenue class are PARALLEL DIMENSIONS, NOT A HIERARCHY
(BUILD_PLAN §3.2). A group is the display row in the product table; the class
is Recurring / Non-Recurring. UMA displays as its own row *and* classes as
Recurring — neither attribute is derived from the other. Do not collapse them.

Mapping grain is `product_cd`, except ELIS (Equities / Options), LEND
(Security Based Lending / Margin) and — since Round 1b — PCS (Situational
Partnership / Private Bank Referral), which split on `product_sub_cd`: the
only groups where `product_cd` alone is insufficient (SCHEMA_SPEC §4). The
client's hierarchy export confirmed PCS covers TWO sub-products; treating PCS
as Situational Partnership alone silently unmapped Private Bank Referral.

Products absent from the seed map to group ``unmapped`` — visible, never
silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RECURRING = "RECURRING"
NON_RECURRING = "NON_RECURRING"

UNMAPPED_GROUP_ID = "unmapped"

# product_id convention (V4): product_id = product_cd || '|' || product_sub_cd
PRODUCT_ID_SEP = "|"


@dataclass(frozen=True)
class ProductGroup:
    """One row of the phx_dm_pce_product_group seed (V3)."""

    sort_order: int
    group_id: str
    group_name: str
    display_prefix: str  # "TWHS" where SCHEMA_SPEC §4 prefix column says TWHS, else ""
    class_id: str  # RECURRING | NON_RECURRING — independent of group_id
    product_cds: list[str] = field(default_factory=list)
    is_aggregated: bool = True


# The 25-row seed from SCHEMA_SPEC §4. Codes with a sub-code split (ELIS/EQ,
# ELIS/OP, LEND/SBL, LEND/MGN, PCS/SP, PCS/PBR) are listed as "CD/SUB" and
# resolved in resolve_product(); every other code maps on product_cd alone.
PRODUCT_GROUPS: list[ProductGroup] = [
    ProductGroup(1, "managed_accounts", "Managed Accounts", "", RECURRING,
                 ["OISC", "OIS1", "JPMC", "MAP"]),
    ProductGroup(2, "managed_uma", "Managed – Unified Managed Accounts", "", RECURRING,
                 ["UMA"]),
    ProductGroup(3, "trails_mutual_funds", "Trails – Mutual Funds", "", RECURRING,
                 ["ATMF"]),
    ProductGroup(4, "trails_life_annuities", "Trails – Life & Annuities", "", RECURRING,
                 ["ITMF", "ADVA"]),
    ProductGroup(5, "cash_mgmt_mmkt", "Cash Management – Money Market Funds", "", RECURRING,
                 ["MMKT"]),
    ProductGroup(6, "cash_mgmt_prdp", "Cash Management – Premium Deposits", "", RECURRING,
                 ["PRDP"]),
    # Round 1b: narrowed from bare PCS to PCS/SP — the hierarchy export shows
    # PCS covers two sub-products. Class RECURRING unchanged (client's earlier
    # instruction stands).
    ProductGroup(7, "referrals_sit_partnership",
                 "Referrals & Revenue Share – Situational Partnership", "", RECURRING,
                 ["PCS/SP"]),
    ProductGroup(8, "plans_529", "529 Plans", "", RECURRING, ["529T"]),
    ProductGroup(9, "donor_advised_funds", "Donor Advised Funds", "", RECURRING, ["DAF"]),
    ProductGroup(10, "twhs_structured", "Structured Products", "TWHS", NON_RECURRING,
                 ["STRT"]),
    ProductGroup(11, "twhs_equities", "Equities", "TWHS", NON_RECURRING, ["ELIS/EQ"]),
    ProductGroup(12, "twhs_options", "Options", "TWHS", NON_RECURRING, ["ELIS/OP"]),
    ProductGroup(13, "twhs_mutual_funds", "Mutual Funds", "TWHS", NON_RECURRING, ["MUFD"]),
    ProductGroup(14, "twhs_fi_corporate", "Fixed Income – Corporate Bonds", "TWHS",
                 NON_RECURRING, ["FCXX"]),
    ProductGroup(15, "twhs_fi_municipal", "Fixed Income – Municipal Bonds", "TWHS",
                 NON_RECURRING, ["FMXX"]),
    ProductGroup(16, "twhs_fi_government", "Fixed Income – Government Bonds", "TWHS",
                 NON_RECURRING, ["FGXX"]),
    ProductGroup(17, "twhs_fi_other", "Fixed Income – Other", "TWHS", NON_RECURRING,
                 ["FCOT"]),
    ProductGroup(18, "twhs_cash_mgmt_cds", "Cash Management – Brokered CDs", "TWHS",
                 NON_RECURRING, ["FCCD"]),
    ProductGroup(19, "life_annuities", "Life & Annuities", "", NON_RECURRING,
                 ["FIX", "VARI", "LIFE"]),
    # Alternative Investments is ASSUMED NON_RECURRING, unconfirmed since V2 R11.
    ProductGroup(20, "alternative_investments", "Alternative Investments", "", NON_RECURRING,
                 ["ALTI"]),
    ProductGroup(21, "defined_contribution_advisory", "Defined Contribution Advisory", "",
                 NON_RECURRING, ["DCCR"]),
    ProductGroup(22, "lending_sbl", "Lending – Security Based Lending", "", NON_RECURRING,
                 ["LEND/SBL"]),
    ProductGroup(23, "lending_margin", "Lending – Margin", "", NON_RECURRING, ["LEND/MGN"]),
    ProductGroup(24, "referrals_everyday_401k",
                 "Referrals & Revenue Share – Everyday 401K", "", NON_RECURRING, ["EDK"]),
    # Round 1b: PCS/PBR was silently unmapped while PCS mapped wholesale to
    # Situational Partnership. NON_RECURRING, matching Everyday 401K and the
    # other referral lines.
    ProductGroup(25, "referrals_private_bank",
                 "Referrals & Revenue Share – Private Bank Referral", "", NON_RECURRING,
                 ["PCS/PBR"]),
]

# Row 99: the catch-all for products absent from the seed. is_aggregated=False —
# it is not one of the 25 real aggregation rows; it exists so unmapped revenue
# stays visible rather than dropped, and the UI can render it distinctly.
UNMAPPED_GROUP = ProductGroup(99, UNMAPPED_GROUP_ID, "Unmapped Products", "",
                              NON_RECURRING, [], is_aggregated=False)

ALL_GROUPS: list[ProductGroup] = PRODUCT_GROUPS + [UNMAPPED_GROUP]

_GROUPS_BY_ID: dict[str, ProductGroup] = {g.group_id: g for g in ALL_GROUPS}

# Lookup tables built once at import time.
# (product_cd, product_sub_cd) -> group_id for the sub-code splits;
# product_cd -> group_id for everything else. Keys are upper-cased canonical codes.
_SUBCODE_MAP: dict[tuple[str, str], str] = {}
_CD_MAP: dict[str, str] = {}
for _g in PRODUCT_GROUPS:
    for _code in _g.product_cds:
        if "/" in _code:
            _cd, _sub = _code.split("/", 1)
            _SUBCODE_MAP[(_cd.upper(), _sub.upper())] = _g.group_id
        else:
            _CD_MAP[_code.upper()] = _g.group_id

# The committed mock data's PCS rows predate the PCS/SP · PCS/PBR split and
# carry an empty sub-code; a sub-less PCS row still means Situational
# Partnership (the export's PBR rows always carry the PBR sub-code). Any
# OTHER unknown PCS sub-code lands in "unmapped", per the ELIS/LEND rule.
_SUBCODE_MAP[("PCS", "")] = "referrals_sit_partnership"


def make_product_id(product_cd: str, product_sub_cd: str = "") -> str:
    """V4 convention: product_id = product_cd || '|' || product_sub_cd."""
    return f"{product_cd}{PRODUCT_ID_SEP}{product_sub_cd}"


def split_product_id(product_id: str) -> tuple[str, str]:
    """Inverse of make_product_id. Tolerates a missing separator."""
    cd, sep, sub = (product_id or "").partition(PRODUCT_ID_SEP)
    return cd, sub


def resolve_product(product_cd: str, product_sub_cd: str = "") -> str:
    """Map (product_cd, product_sub_cd) to a group_id.

    Never raises and never drops: anything not in the §4 seed resolves to
    "unmapped". Comparison is whitespace/case robust (strip + upper), but the
    seed stores canonical codes exactly as the spec writes them.
    """
    cd = (product_cd or "").strip().upper()
    sub = (product_sub_cd or "").strip().upper()
    group_id = _SUBCODE_MAP.get((cd, sub))
    if group_id is not None:
        return group_id
    # A code that only exists with sub-code splits (ELIS, LEND) must not fall
    # through to a cd-only match; _CD_MAP simply has no entry for it, so an
    # unknown sub-code lands in "unmapped" as required.
    return _CD_MAP.get(cd, UNMAPPED_GROUP_ID)


def class_for_group(group_id: str) -> str:
    """RECURRING | NON_RECURRING for a group_id; unknown ids class as the
    unmapped group's class (NON_RECURRING) rather than raising."""
    group = _GROUPS_BY_ID.get((group_id or "").strip())
    return group.class_id if group is not None else UNMAPPED_GROUP.class_id


def revenue_class_rows() -> list[dict]:
    """The two phx_dm_pce_revenue_class rows (V2 seed), CSV attribute order."""
    return [
        {"class_id": RECURRING, "class_name": "Recurring"},
        {"class_id": NON_RECURRING, "class_name": "Non-Recurring"},
    ]


def product_group_rows() -> list[dict]:
    """The 26 phx_dm_pce_product_group rows (25 seed + unmapped), columns in
    V3 DDL attribute order: group_id, group_name, display_prefix, class_id,
    sort_order, is_aggregated."""
    return [
        {
            "group_id": g.group_id,
            "group_name": g.group_name,
            "display_prefix": g.display_prefix,
            "class_id": g.class_id,
            "sort_order": g.sort_order,
            "is_aggregated": g.is_aggregated,
        }
        for g in ALL_GROUPS
    ]
