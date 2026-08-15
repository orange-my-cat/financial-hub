"""CSV export — the only route data has out of this application.

Promoted from *Could* to **Must** (departure D1), because with no import path
and no integrations, this is the sole way the user's decade of typing leaves the
system in a form anything else can read. The dump handles disaster recovery;
this handles portability and the freedom to go elsewhere.

**Generated server-side, from the same services the screens use.** An export
built in the browser would carry rounded display values, and a figure that
disagrees with the screen it came from is worse than no export at all. Nothing
here recomputes anything: every row comes out of the net worth service, the
category report or the replay engine.

Two things are carried into the file that a naive export would drop:

  * **Rate provenance and completeness** travel as header rows on the net worth
    export. A total whose qualifications were stripped on the way out is a total
    someone will quote later without them.
  * **Every net-of-tax figure is labelled indicative**, in the file, on the row.
    BR-21 says on every screen *and export*, and an export is precisely where a
    figure acquires unearned authority.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from core.months import sequence


def _writer() -> tuple[io.StringIO, "csv._writer"]:
    buffer = io.StringIO()
    return buffer, csv.writer(buffer, lineterminator="\n")


def net_worth_csv(month: str, currency: str) -> str:
    from accounts.services.net_worth import NetWorthService
    from core.models import Settings

    service = NetWorthService(staleness_days=Settings.load().rate_staleness_days)
    result = service.for_month(month, currency)

    buffer, out = _writer()

    # The qualifications ride along with the figure. Stripping them on the way
    # out is how a total gets quoted later without them.
    out.writerow(["Financial Hub — net worth"])
    out.writerow(["Month", month])
    out.writerow(["Reporting currency", currency])
    out.writerow(["Completeness", str(result.completeness.state)])
    out.writerow(
        [
            "Balances recorded",
            f"{result.completeness.balances_recorded} of {result.completeness.balances_expected}",
        ]
    )
    if result.any_stale and result.oldest_as_at:
        out.writerow(["Oldest contributing rate", result.oldest_as_at.isoformat()])
    for exclusion in result.exclusion_notices():
        out.writerow(["Excluded", exclusion["account"], exclusion["reason"]])
    out.writerow([])

    out.writerow(
        [
            "Account",
            "Type",
            "Liquidity tier",
            "Status",
            "Currency",
            "Entered",
            "Source month",
            "Carried",
            f"Translated ({currency})",
            "Rate as at",
            "Provenance",
            "Stale",
            "Excluded",
        ]
    )
    for contribution in result.contributions:
        row = contribution.as_dict()
        out.writerow(
            [
                row["name"],
                row["type"],
                row["liquidity_tier"],
                row["status"],
                row["currency"],
                row["entered"]["amount"],
                row["source_month"],
                "yes" if row["carried"] else "",
                row["translated"] or "excluded",
                row["as_at"] or "",
                row["provenance"] or "",
                "yes" if row["stale"] else "",
                row["exclusion_reason"] or "",
            ]
        )

    out.writerow([])
    out.writerow(["Net worth", result.total.api()["amount"], currency])

    return buffer.getvalue()


def net_worth_trend_csv(from_month: str, to_month: str, currency: str) -> str:
    from accounts.services.net_worth import NetWorthService
    from core.models import Settings

    service = NetWorthService(staleness_days=Settings.load().rate_staleness_days)
    months = list(sequence(from_month, to_month))

    buffer, out = _writer()
    out.writerow(["Financial Hub — net worth trend"])
    out.writerow(["Reporting currency", currency])
    out.writerow([])
    out.writerow(["Month", f"Net worth ({currency})", "Completeness", "Excluded accounts"])

    for result in service.trend(months, currency):
        out.writerow(
            [
                result.month,
                # Blank, not zero: a month before any balance existed does not
                # have a net worth.
                result.total.api()["amount"] if result.is_reportable else "",
                str(result.completeness.state),
                len(result.exclusions) or "",
            ]
        )

    return buffer.getvalue()


def cashflow_csv(month: str) -> str:
    from cashflow.services.reporting import category_report, transactions_for_month

    buffer, out = _writer()
    out.writerow(["Financial Hub — cash flow"])
    out.writerow(["Month", month])
    out.writerow(
        [
            "Note",
            "Amounts are in the currency each transaction was entered in and are "
            "never translated. No figure here relates to any account balance.",
        ]
    )
    out.writerow([])

    out.writerow(["Date", "Direction", "Parent", "Category", "Note", "Amount", "Currency"])
    for row in transactions_for_month(month):
        out.writerow(
            [
                row["date"],
                row["direction"],
                row["parent"],
                row["category"],
                row["note"],
                row["amount"],
                row["currency"],
            ]
        )

    out.writerow([])
    out.writerow(["Currency", "Income", "Expense", "Net"])
    for block in category_report(month):
        out.writerow([block["currency"], block["income"], block["expense"], block["net"]])

    return buffer.getvalue()


def investments_csv(year: int | None = None) -> str:
    from investments.services.positions import positions, realised_gains_by_currency

    buffer, out = _writer()
    out.writerow(["Financial Hub — investments"])
    out.writerow(
        [
            "Note",
            "Figures are in each holding's own currency and are never translated. "
            "Unrealised gain does not exist in this system: no market prices are held.",
        ]
    )
    out.writerow([])

    out.writerow(
        ["Holding", "Symbol", "Account", "Currency", "Quantity", "Cost basis", "Open lots", "Consistent"]
    )
    for position in positions():
        row = position.as_dict()
        out.writerow(
            [
                row["name"],
                row["symbol"],
                row["account"],
                row["currency"],
                row["total_quantity"],
                row["total_cost_basis"],
                row["lot_count"],
                "yes" if row["consistent"] else "FLAGGED — see the application",
            ]
        )

    out.writerow([])
    out.writerow(
        [
            "Sale date",
            "Holding",
            "Currency",
            "Quantity",
            "Proceeds",
            "Fees",
            "Net proceeds",
            "Cost basis",
            "Gross realised gain",
            "Estimated tax %",
            "Net realised gain",
            "Basis of net figure",
        ]
    )
    for block in realised_gains_by_currency(year):
        for sale in block["sales"]:
            out.writerow(
                [
                    sale["date"],
                    sale["holding"],
                    block["currency"],
                    sale["quantity"],
                    sale["proceeds"],
                    sale["fees"],
                    sale["net_proceeds"],
                    sale["cost_basis"],
                    sale["realised_gain"],
                    sale["estimated_tax_percent"] or "",
                    sale["net_realised_gain"],
                    # BR-21 — on every screen AND export. An export is exactly
                    # where an indicative figure acquires unearned authority.
                    "INDICATIVE — a percentage you supplied, not a tax calculation"
                    if sale["tax_applied"]
                    else "no estimate applied",
                ]
            )
        out.writerow(
            [
                f"Total, {block['currency']} only",
                "",
                block["currency"],
                "",
                "",
                "",
                "",
                "",
                block["gross"],
                "",
                block["net"],
                "INDICATIVE" if block["tax_applied"] else "",
            ]
        )

    return buffer.getvalue()


def fx_csv(start: date, end: date) -> str:
    from core.models import Settings
    from fx.services.reporting import daily_rates

    buffer, out = _writer()
    out.writerow(["Financial Hub — exchange rates"])
    out.writerow(["From", start.isoformat(), "To", end.isoformat()])
    out.writerow([])
    out.writerow(["Date", "Pair", "Quoted as", "Rate", "As at", "Provenance", "Stale", "Recorded"])

    for row in daily_rates(start, end, staleness_days=Settings.load().rate_staleness_days):
        for entry in row.entries:
            payload = entry.as_dict()
            out.writerow(
                [
                    row.on_date.isoformat(),
                    payload["pair"],
                    payload["quote_label"],
                    payload["rate"],
                    payload["as_at"],
                    payload["provenance"],
                    "yes" if payload["stale"] else "",
                    "yes" if payload["recorded"] else "",
                ]
            )

    return buffer.getvalue()
