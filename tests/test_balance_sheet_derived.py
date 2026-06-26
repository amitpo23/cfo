"""The derived balance sheet must be flagged derived + disclaimer (parity with ledger).

financial_reports_service.generate_balance_sheet derives the balance sheet from synced
document movements. Like ledger_service.balance_sheet, its serialized form must carry
`derived: true` and a "לבדיקת רו"ח" disclaimer so it is never presented as official books.
"""
from cfo.services.financial_reports_service import BalanceSheetReport


def _empty_report() -> BalanceSheetReport:
    return BalanceSheetReport(
        as_of_date="2026-06-30",
        current_assets=[],
        total_current_assets=0.0,
        fixed_assets=[],
        total_fixed_assets=0.0,
        other_assets=[],
        total_other_assets=0.0,
        total_assets=0.0,
        current_liabilities=[],
        total_current_liabilities=0.0,
        long_term_liabilities=[],
        total_long_term_liabilities=0.0,
        total_liabilities=0.0,
        equity=[],
        total_equity=0.0,
        total_liabilities_and_equity=0.0,
        is_balanced=True,
    )


def test_balance_sheet_to_dict_is_flagged_derived():
    out = _empty_report().to_dict()
    assert out.get("derived") is True
    assert "לבדיקת רו" in out.get("disclaimer", "")


def test_balance_sheet_to_dict_still_carries_core_fields():
    out = _empty_report().to_dict()
    assert out["as_of_date"] == "2026-06-30"
    assert out["is_balanced"] is True
    assert "total_assets" in out
