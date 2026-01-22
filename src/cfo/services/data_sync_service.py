"""
Data Sync Service - Integration with SUMIT API
שירות סנכרון נתונים מ-SUMIT API
"""
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date, timedelta
from decimal import Decimal
import asyncio
import logging
from sqlalchemy.orm import Session

from ..integrations.sumit_integration import SumitIntegration
from ..integrations.sumit_models import DocumentListRequest, DebtReportRequest
from ..models import (
    Transaction, Account, Organization, TransactionType, AccountType
)
from ..config import settings

logger = logging.getLogger(__name__)


class DataSyncService:
    """
    שירות סנכרון נתונים מ-SUMIT API למסד הנתונים המקומי
    Synchronizes data from SUMIT API to local database for analysis
    """
    
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id
        self._sumit: Optional[SumitIntegration] = None
    
    async def _get_sumit(self) -> SumitIntegration:
        """Get or create SUMIT integration instance"""
        if self._sumit is None:
            # קבלת credentials מהארגון
            org = self.db.query(Organization).filter(
                Organization.id == self.organization_id
            ).first()
            
            if org and org.api_credentials:
                api_key = org.api_credentials.get('api_key') or settings.sumit_api_key
                company_id = org.api_credentials.get('company_id') or settings.sumit_company_id
            else:
                api_key = settings.sumit_api_key
                company_id = settings.sumit_company_id
            
            if not api_key:
                raise ValueError("SUMIT API key not configured")
            
            self._sumit = SumitIntegration(api_key=api_key, company_id=company_id)
        
        return self._sumit
    
    async def close(self):
        """Close SUMIT connection"""
        if self._sumit:
            await self._sumit.__aexit__(None, None, None)
            self._sumit = None
    
    # ============= Document Sync =============
    
    async def sync_documents(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        document_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        סנכרון מסמכים מ-SUMIT (חשבוניות, קבלות וכו')
        Sync documents from SUMIT (invoices, receipts, etc.)
        """
        sumit = await self._get_sumit()
        
        if not from_date:
            from_date = date.today() - timedelta(days=90)
        if not to_date:
            to_date = date.today()
        
        async with sumit:
            # שליפת מסמכים
            request = DocumentListRequest(
                from_date=from_date,
                to_date=to_date,
                document_types=document_types
            )
            
            documents = await sumit.list_documents(request)
            
            synced_count = 0
            total_income = Decimal("0")
            total_expenses = Decimal("0")
            
            for doc in documents:
                # בדיקה אם המסמך כבר קיים
                existing = self.db.query(Transaction).filter(
                    Transaction.external_id == str(doc.id),
                    Transaction.organization_id == self.organization_id
                ).first()
                
                if existing:
                    continue
                
                # קביעת סוג העסקה
                is_income = doc.document_type in ['invoice', 'receipt', 'tax_invoice']
                tx_type = TransactionType.INCOME if is_income else TransactionType.EXPENSE
                
                # מציאת או יצירת חשבון ברירת מחדל
                account = self._get_or_create_default_account(
                    AccountType.REVENUE if is_income else AccountType.EXPENSE
                )
                
                # יצירת עסקה
                transaction = Transaction(
                    organization_id=self.organization_id,
                    account_id=account.id,
                    transaction_type=tx_type,
                    amount=doc.total or Decimal("0"),
                    description=f"{doc.document_type}: {doc.customer_name or 'Unknown'}",
                    category=self._map_document_type_to_category(doc.document_type),
                    transaction_date=doc.date or datetime.now(),
                    external_id=str(doc.id)
                )
                
                self.db.add(transaction)
                synced_count += 1
                
                if is_income:
                    total_income += doc.total or Decimal("0")
                else:
                    total_expenses += doc.total or Decimal("0")
            
            self.db.commit()
            
            return {
                'synced_documents': synced_count,
                'total_income': float(total_income),
                'total_expenses': float(total_expenses),
                'period': {
                    'from': from_date.isoformat(),
                    'to': to_date.isoformat()
                }
            }
    
    async def sync_payments(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        סנכרון תשלומים מ-SUMIT
        Sync payments from SUMIT
        """
        sumit = await self._get_sumit()
        
        if not from_date:
            from_date = date.today() - timedelta(days=90)
        if not to_date:
            to_date = date.today()
        
        async with sumit:
            payments = await sumit.list_payments(
                from_date=from_date,
                to_date=to_date
            )
            
            synced_count = 0
            total_amount = Decimal("0")
            
            for payment in payments:
                # בדיקה אם התשלום כבר קיים
                existing = self.db.query(Transaction).filter(
                    Transaction.external_id == f"payment_{payment.id}",
                    Transaction.organization_id == self.organization_id
                ).first()
                
                if existing:
                    continue
                
                # חשבון הכנסות
                account = self._get_or_create_default_account(AccountType.REVENUE)
                
                # יצירת עסקה
                transaction = Transaction(
                    organization_id=self.organization_id,
                    account_id=account.id,
                    transaction_type=TransactionType.INCOME,
                    amount=payment.amount or Decimal("0"),
                    description=f"Payment: {payment.description or 'No description'}",
                    category='sales',
                    transaction_date=payment.date or datetime.now(),
                    external_id=f"payment_{payment.id}"
                )
                
                self.db.add(transaction)
                synced_count += 1
                total_amount += payment.amount or Decimal("0")
            
            self.db.commit()
            
            return {
                'synced_payments': synced_count,
                'total_amount': float(total_amount),
                'period': {
                    'from': from_date.isoformat(),
                    'to': to_date.isoformat()
                }
            }
    
    async def sync_billing_transactions(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        סנכרון עסקאות סליקה מ-SUMIT
        Sync billing/credit card transactions from SUMIT
        """
        sumit = await self._get_sumit()
        
        if not from_date:
            from_date = date.today() - timedelta(days=30)
        if not to_date:
            to_date = date.today()
        
        async with sumit:
            from ..integrations.sumit_models import BillingTransactionRequest
            
            request = BillingTransactionRequest(
                from_date=from_date,
                to_date=to_date
            )
            
            transactions = await sumit.load_billing_transactions(request)
            
            synced_count = 0
            total_amount = Decimal("0")
            
            for tx in transactions:
                # בדיקה אם העסקה כבר קיימת
                existing = self.db.query(Transaction).filter(
                    Transaction.external_id == f"billing_{tx.id}",
                    Transaction.organization_id == self.organization_id
                ).first()
                
                if existing:
                    continue
                
                account = self._get_or_create_default_account(AccountType.REVENUE)
                
                transaction = Transaction(
                    organization_id=self.organization_id,
                    account_id=account.id,
                    transaction_type=TransactionType.INCOME,
                    amount=tx.amount or Decimal("0"),
                    description=f"Card Transaction: {tx.card_last_digits or 'XXXX'}",
                    category='sales',
                    transaction_date=tx.date or datetime.now(),
                    external_id=f"billing_{tx.id}"
                )
                
                self.db.add(transaction)
                synced_count += 1
                total_amount += tx.amount or Decimal("0")
            
            self.db.commit()
            
            return {
                'synced_billing_transactions': synced_count,
                'total_amount': float(total_amount),
                'period': {
                    'from': from_date.isoformat(),
                    'to': to_date.isoformat()
                }
            }
    
    async def sync_debt_report(self) -> Dict[str, Any]:
        """
        סנכרון דוח חובות מ-SUMIT
        Sync debt report from SUMIT
        """
        sumit = await self._get_sumit()
        
        async with sumit:
            request = DebtReportRequest()
            debts = await sumit.get_debt_report(request)
            
            total_receivable = Decimal("0")
            total_payable = Decimal("0")
            debt_items = []
            
            for debt in debts:
                amount = Decimal(str(debt.get('amount', 0)))
                customer_name = debt.get('customer_name', 'Unknown')
                due_date = debt.get('due_date')
                
                if amount > 0:
                    total_receivable += amount
                else:
                    total_payable += abs(amount)
                
                debt_items.append({
                    'customer_name': customer_name,
                    'amount': float(amount),
                    'due_date': due_date,
                    'days_overdue': debt.get('days_overdue', 0)
                })
            
            return {
                'total_receivable': float(total_receivable),
                'total_payable': float(total_payable),
                'debt_items': debt_items,
                'count': len(debt_items)
            }
    
    async def sync_income_items(self) -> Dict[str, Any]:
        """
        סנכרון פריטי הכנסה מ-SUMIT
        Sync income items from SUMIT
        """
        sumit = await self._get_sumit()
        
        async with sumit:
            items = await sumit.list_income_items()
            
            return {
                'income_items': [
                    {
                        'id': item.id,
                        'name': item.name,
                        'price': float(item.price) if item.price else 0,
                        'description': item.description
                    }
                    for item in items
                ],
                'count': len(items)
            }
    
    async def get_vat_rate(self, for_date: Optional[date] = None) -> float:
        """
        קבלת שיעור מע"מ מ-SUMIT
        Get current VAT rate from SUMIT
        """
        sumit = await self._get_sumit()
        
        async with sumit:
            vat_rate = await sumit.get_vat_rate(for_date)
            return float(vat_rate)
    
    async def get_exchange_rate(
        self,
        from_currency: str,
        to_currency: str = "ILS"
    ) -> float:
        """
        קבלת שער חליפין מ-SUMIT
        Get exchange rate from SUMIT
        """
        sumit = await self._get_sumit()
        
        async with sumit:
            from ..integrations.sumit_models import ExchangeRateRequest
            
            request = ExchangeRateRequest(
                from_currency=from_currency,
                to_currency=to_currency
            )
            
            result = await sumit.get_exchange_rate(request)
            return float(result.rate) if result.rate else 0
    
    async def sync_all(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        סנכרון מלא של כל הנתונים
        Full sync of all data from SUMIT
        """
        results = {}
        
        try:
            # סנכרון מסמכים
            results['documents'] = await self.sync_documents(from_date, to_date)
        except Exception as e:
            logger.error(f"Document sync failed: {e}")
            results['documents'] = {'error': str(e)}
        
        try:
            # סנכרון תשלומים
            results['payments'] = await self.sync_payments(from_date, to_date)
        except Exception as e:
            logger.error(f"Payment sync failed: {e}")
            results['payments'] = {'error': str(e)}
        
        try:
            # סנכרון עסקאות סליקה
            results['billing'] = await self.sync_billing_transactions(from_date, to_date)
        except Exception as e:
            logger.error(f"Billing sync failed: {e}")
            results['billing'] = {'error': str(e)}
        
        try:
            # סנכרון דוח חובות
            results['debts'] = await self.sync_debt_report()
        except Exception as e:
            logger.error(f"Debt report sync failed: {e}")
            results['debts'] = {'error': str(e)}
        
        await self.close()
        
        return results
    
    # ============= Helper Methods =============
    
    def _get_or_create_default_account(self, account_type: AccountType) -> Account:
        """Get or create default account for organization"""
        account = self.db.query(Account).filter(
            Account.organization_id == self.organization_id,
            Account.account_type == account_type
        ).first()
        
        if not account:
            name_map = {
                AccountType.ASSET: 'נכסים',
                AccountType.LIABILITY: 'התחייבויות',
                AccountType.EQUITY: 'הון עצמי',
                AccountType.REVENUE: 'הכנסות',
                AccountType.EXPENSE: 'הוצאות'
            }
            
            account = Account(
                organization_id=self.organization_id,
                name=name_map.get(account_type, 'חשבון כללי'),
                account_type=account_type,
                balance=Decimal("0"),
                currency="ILS"
            )
            self.db.add(account)
            self.db.commit()
            self.db.refresh(account)
        
        return account
    
    def _map_document_type_to_category(self, doc_type: str) -> str:
        """Map SUMIT document type to transaction category"""
        mapping = {
            'invoice': 'sales',
            'tax_invoice': 'sales',
            'receipt': 'sales',
            'credit_invoice': 'sales',
            'quote': 'sales',
            'delivery_note': 'sales',
            'order': 'sales',
            'expense': 'supplies',
            'expense_invoice': 'supplies',
        }
        return mapping.get(doc_type, 'other')
