from datetime import date
from cfo.database import SessionLocal
from cfo.models import Account, AccountType, Contact, ContactType, Invoice, InvoiceStatus, BankTransaction
from cfo.services.financial_reports_service import FinancialReportsService


def test_projection_separates_unpaid_receivable_actual_cash_and_unknown_balance(fresh_org):
    org = fresh_org()['org_id']
    with SessionLocal() as db:
        contact = Contact(organization_id=org, name='Buyer', contact_type=ContactType.CUSTOMER)
        db.add(contact); db.flush()
        db.add(Invoice(organization_id=org, contact_id=contact.id, invoice_number='part-paid',
                       issue_date=date(2026,1,2), due_date=date(2026,2,1), subtotal=1000, tax=0,
                       total=1000, paid_amount=400, balance=600, status=InvoiceStatus.SENT))
        db.add(Account(organization_id=org, name='Office equipment', account_type=AccountType.ASSET, balance=90000))
        db.add(BankTransaction(organization_id=org, transaction_date=date(2026,1,3), amount=400, description='Partial payment'))
        db.commit()
        result = FinancialReportsService(db).generate_cash_flow_projection(org, months=3, as_of_date=date(2026,1,31))
        assert result.historical_average_inflows == round(400/3, 2)
        assert result.ending_balance is None
        assert result.runway_months is None
        assert [p.month for p in result.projections] == ['2026-01','2026-02','2026-03']
        assert result.total_projected_inflows == 600
        assert result.projections[1].inflows == 600
        assert result.balance_basis == 'unavailable'
        assert FinancialReportsService(db).export_cash_flow_projection_excel(result)


def test_projection_no_data_is_not_a_zero_forecast(fresh_org):
    with SessionLocal() as db:
        result = FinancialReportsService(db).generate_cash_flow_projection(fresh_org()['org_id'], months=3)
        assert result.projections == []
        assert result.historical_average_inflows is None
        assert result.ending_balance is None
        assert result.message
        assert FinancialReportsService(db).export_cash_flow_projection_excel(result)
