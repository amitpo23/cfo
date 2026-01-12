"""
Financial operations service
שירות לפעולות פיננסיות
"""
from typing import List, Optional
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from ..models import (
    Account, Transaction, AccountType, TransactionType,
    AccountCreate, TransactionCreate, FinancialSummary
)


class FinancialService:
    """שירות לניהול פעולות פיננסיות"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_account(self, account_data: AccountCreate) -> Account:
        """יצירת חשבון חדש"""
        account = Account(
            name=account_data.name,
            account_type=account_data.account_type,
            balance=account_data.balance,
            currency=account_data.currency
        )
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account
    
    def get_account(self, account_id: int) -> Optional[Account]:
        """שליפת חשבון לפי ID"""
        return self.db.query(Account).filter(Account.id == account_id).first()
    
    def get_all_accounts(self) -> List[Account]:
        """שליפת כל החשבונות"""
        return self.db.query(Account).all()
    
    def create_transaction(self, transaction_data: TransactionCreate) -> Transaction:
        """יצירת עסקה חדשה ועדכון יתרת החשבון"""
        # בדיקה שהחשבון קיים
        account = self.get_account(transaction_data.account_id)
        if not account:
            raise ValueError(f"Account {transaction_data.account_id} not found")
        
        # יצירת העסקה
        transaction = Transaction(
            account_id=transaction_data.account_id,
            transaction_type=transaction_data.transaction_type,
            amount=transaction_data.amount,
            description=transaction_data.description,
            category=transaction_data.category,
            transaction_date=transaction_data.transaction_date
        )
        
        # עדכון יתרת החשבון
        if transaction_data.transaction_type == TransactionType.INCOME:
            account.balance += transaction_data.amount
        elif transaction_data.transaction_type == TransactionType.EXPENSE:
            account.balance -= transaction_data.amount
        
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)
        return transaction
    
    def get_transactions(
        self,
        account_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        transaction_type: Optional[TransactionType] = None,
        limit: int = 100
    ) -> List[Transaction]:
        """שליפת עסקאות לפי פילטרים"""
        query = self.db.query(Transaction)
        
        if account_id:
            query = query.filter(Transaction.account_id == account_id)
        
        if start_date:
            query = query.filter(Transaction.transaction_date >= start_date)
        
        if end_date:
            query = query.filter(Transaction.transaction_date <= end_date)
        
        if transaction_type:
            query = query.filter(Transaction.transaction_type == transaction_type)
        
        return query.order_by(Transaction.transaction_date.desc()).limit(limit).all()
    
    def get_financial_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> FinancialSummary:
        """קבלת סיכום פיננסי לתקופה"""
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()
        
        # חישוב סך נכסים
        total_assets = self.db.query(func.sum(Account.balance)).filter(
            Account.account_type == AccountType.ASSET
        ).scalar() or Decimal("0")
        
        # חישוב סך התחייבויות
        total_liabilities = self.db.query(func.sum(Account.balance)).filter(
            Account.account_type == AccountType.LIABILITY
        ).scalar() or Decimal("0")
        
        # חישוב סך הכנסות בתקופה
        total_income = self.db.query(func.sum(Transaction.amount)).filter(
            and_(
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).scalar() or Decimal("0")
        
        # חישוב סך הוצאות בתקופה
        total_expenses = self.db.query(func.sum(Transaction.amount)).filter(
            and_(
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).scalar() or Decimal("0")
        
        return FinancialSummary(
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            net_worth=total_assets - total_liabilities,
            total_income=total_income,
            total_expenses=total_expenses,
            net_income=total_income - total_expenses,
            period_start=start_date,
            period_end=end_date
        )
    
    def get_account_balance(self, account_id: int) -> Decimal:
        """קבלת יתרת חשבון"""
        account = self.get_account(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        return account.balance
