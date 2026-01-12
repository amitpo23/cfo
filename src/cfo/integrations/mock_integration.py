"""
Mock integration for testing and demo purposes
אינטגרציה מדומה למטרות בדיקה והדגמה
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal
import random

from .base import BaseAccountingIntegration


class MockAccountingIntegration(BaseAccountingIntegration):
    """מערכת הנהלת חשבונות מדומה לצורך פיתוח ובדיקות"""
    
    def __init__(self, client_id: str = "mock", client_secret: str = "mock", **kwargs):
        super().__init__(client_id, client_secret, **kwargs)
        self._generate_mock_data()
    
    def _generate_mock_data(self):
        """יצירת נתונים מדומים"""
        self.mock_accounts = [
            {
                "id": "acc_001",
                "name": "חשבון עו\"ש ראשי",
                "type": "asset",
                "balance": Decimal("150000.00"),
                "currency": "ILS"
            },
            {
                "id": "acc_002",
                "name": "קופה",
                "type": "asset",
                "balance": Decimal("5000.00"),
                "currency": "ILS"
            },
            {
                "id": "acc_003",
                "name": "הכנסות משירותים",
                "type": "revenue",
                "balance": Decimal("0.00"),
                "currency": "ILS"
            },
            {
                "id": "acc_004",
                "name": "הוצאות שכר",
                "type": "expense",
                "balance": Decimal("0.00"),
                "currency": "ILS"
            },
        ]
        
        # יצירת עסקאות מדומות
        self.mock_transactions = []
        base_date = datetime.now() - timedelta(days=90)
        
        for i in range(50):
            trans_date = base_date + timedelta(days=random.randint(0, 90))
            trans_type = random.choice(["income", "expense"])
            
            if trans_type == "income":
                account_id = "acc_003"
                description = random.choice([
                    "תשלום מלקוח",
                    "הכנסה משירות ייעוץ",
                    "מכירת מוצר"
                ])
            else:
                account_id = "acc_004"
                description = random.choice([
                    "משכורות",
                    "שכר דירה",
                    "ציוד משרדי",
                    "חשמל ומים"
                ])
            
            self.mock_transactions.append({
                "id": f"trans_{i:03d}",
                "account_id": account_id,
                "type": trans_type,
                "amount": Decimal(str(random.uniform(500, 10000))).quantize(Decimal("0.01")),
                "description": description,
                "date": trans_date,
                "category": random.choice(["מכירות", "שכר", "תפעול", "שיווק"])
            })
    
    async def connect(self) -> bool:
        """התחברות למערכת המדומה"""
        self.is_connected = True
        return True
    
    async def disconnect(self):
        """ניתוק מהמערכת"""
        self.is_connected = False
    
    async def get_accounts(self) -> List[Dict[str, Any]]:
        """שליפת רשימת חשבונות"""
        if not self.is_connected:
            raise ConnectionError("Not connected to accounting system")
        return self.mock_accounts
    
    async def get_transactions(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        account_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """שליפת עסקאות"""
        if not self.is_connected:
            raise ConnectionError("Not connected to accounting system")
        
        transactions = self.mock_transactions
        
        if start_date:
            transactions = [t for t in transactions if t["date"] >= start_date]
        
        if end_date:
            transactions = [t for t in transactions if t["date"] <= end_date]
        
        if account_id:
            transactions = [t for t in transactions if t["account_id"] == account_id]
        
        return transactions
    
    async def create_transaction(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """יצירת עסקה חדשה"""
        if not self.is_connected:
            raise ConnectionError("Not connected to accounting system")
        
        new_trans = {
            "id": f"trans_{len(self.mock_transactions):03d}",
            **transaction_data,
            "date": transaction_data.get("date", datetime.now())
        }
        self.mock_transactions.append(new_trans)
        return new_trans
    
    async def get_balance_sheet(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """שליפת מאזן"""
        if not self.is_connected:
            raise ConnectionError("Not connected to accounting system")
        
        assets = sum(
            acc["balance"] for acc in self.mock_accounts
            if acc["type"] == "asset"
        )
        
        return {
            "date": date or datetime.now(),
            "assets": {
                "current_assets": assets,
                "total_assets": assets
            },
            "liabilities": {
                "current_liabilities": Decimal("20000.00"),
                "total_liabilities": Decimal("20000.00")
            },
            "equity": assets - Decimal("20000.00")
        }
    
    async def get_profit_loss(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """שליפת דוח רווח והפסד"""
        if not self.is_connected:
            raise ConnectionError("Not connected to accounting system")
        
        transactions = await self.get_transactions(start_date, end_date)
        
        total_income = sum(
            t["amount"] for t in transactions
            if t["type"] == "income"
        )
        
        total_expenses = sum(
            t["amount"] for t in transactions
            if t["type"] == "expense"
        )
        
        return {
            "period_start": start_date,
            "period_end": end_date,
            "revenue": total_income,
            "expenses": total_expenses,
            "net_income": total_income - total_expenses,
            "breakdown": {
                "revenue_by_category": {},
                "expenses_by_category": {}
            }
        }
