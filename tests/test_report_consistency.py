"""A management report must not undo accounting corrections in the ledger."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Expense
from cfo.services import ledger_service
from cfo.services.financial_reports_service import FinancialReportsService

START, END = date(2026, 5, 1), date(2026, 5, 31)


def test_pnl_deduplicates_the_same_document_as_trial_balance(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        db.add(Bill(organization_id=org, external_id='one-document', source='sumit',
                    bill_number='A', issue_date=START, subtotal=1000, tax=180,
                    total=1180, status=BillStatus.RECEIVED))
        db.add(Expense(organization_id=org, external_id='one-document', source='sumit',
                       supplier_name='Supplier', expense_date=START, amount=1000,
                       vat_amount=180, total=1180, status='filed'))
        db.commit()
        tb = ledger_service.trial_balance(db, org, start=START, end=END)
        pl = FinancialReportsService(db).generate_profit_loss(org, START, END, False)
        expense = next(a for a in tb['accounts'] if a['account'] == '5000')
        assert pl.total_expenses == expense['balance'] == 1000


def test_manual_and_payroll_journal_entries_flow_into_pnl(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        ledger_service.add_manual_entry(db, org, entry_date=START, memo='Revenue',
            lines=[{'account':'1100','debit':1000}, {'account':'4000','credit':1000}])
        ledger_service.add_payroll_entry(db, org, entry_date=START, memo='Payroll',
            lines=[{'account':'5100','debit':300}, {'account':'2110','credit':300}],
            external_id='payroll-once')
        db.commit()
        pl = FinancialReportsService(db).generate_profit_loss(org, START, END, False)
        assert pl.total_revenue == 1000
        assert pl.total_expenses == 300
        assert pl.net_income_before_tax == 700


def test_supplier_credit_reduces_expenses(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        db.add_all([
            Bill(organization_id=org, bill_number='invoice', issue_date=START,
                 subtotal=1000, tax=180, total=1180, status=BillStatus.RECEIVED),
            Bill(organization_id=org, bill_number='credit', issue_date=START,
                 subtotal=-200, tax=-36, total=-236, status=BillStatus.RECEIVED,
                 raw_data={'document_type':'credit_note'}),
        ])
        db.commit()
        pl = FinancialReportsService(db).generate_profit_loss(org, START, END, False)
        assert pl.total_expenses == 800
