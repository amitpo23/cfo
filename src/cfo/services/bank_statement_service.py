"""
Bank Statement Import Service
שירות קליטת דפי בנק
"""
import re
import csv
import io
import json
import logging
from typing import List, Optional, Dict, Any, Tuple, Union
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Transaction, Account, AccountType, TransactionType
from ..config import settings

logger = logging.getLogger(__name__)


class BankFormat(str, Enum):
    """פורמטים נתמכים לדפי בנק"""
    LEUMI = "leumi"
    HAPOALIM = "hapoalim"
    DISCOUNT = "discount"
    MIZRAHI = "mizrahi"
    ISRACARD = "isracard"
    CAL = "cal"
    MAX = "max"
    GENERIC = "generic"
    AUTO = "auto"


@dataclass
class BankTransaction:
    """עסקת בנק"""
    date: date
    description: str
    amount: Decimal
    balance: Optional[Decimal] = None
    reference: Optional[str] = None
    transaction_type: Optional[str] = None
    category: Optional[str] = None
    is_debit: bool = False
    raw_data: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            'date': self.date.isoformat(),
            'description': self.description,
            'amount': float(self.amount),
            'balance': float(self.balance) if self.balance else None,
            'reference': self.reference,
            'transaction_type': self.transaction_type,
            'category': self.category,
            'is_debit': self.is_debit
        }


class BankStatementParser:
    """
    מנתח דפי בנק - תומך במספר פורמטים
    """
    
    # תבניות תאריכים נפוצות
    DATE_FORMATS = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%Y/%m/%d"
    ]
    
    # מיפוי קטגוריות על פי תיאור
    CATEGORY_PATTERNS = {
        'salary': [
            r'משכורת', r'שכר', r'salary', r'wage', r'ביטוח לאומי',
            r'פנסיה', r'pension', r'קופת גמל', r'קרן השתלמות'
        ],
        'utilities': [
            r'חשמל', r'מים', r'גז', r'ארנונה', r'עירייה',
            r'electric', r'water', r'gas', r'בזק', r'סלקום', r'פרטנר', r'הוט'
        ],
        'rent': [
            r'שכירות', r'rent', r'משכון', r'מקדמה', r'דמי שכירות'
        ],
        'groceries': [
            r'רמי לוי', r'שופרסל', r'מגה', r'יוחננוף', r'ויקטורי',
            r'אושר עד', r'supermarket', r'food', r'מכולת'
        ],
        'transportation': [
            r'דלק', r'פז', r'סונול', r'דור אלון', r'fuel', r'gas station',
            r'רכבת', r'אגד', r'דן', r'bus', r'train', r'uber', r'gett'
        ],
        'insurance': [
            r'ביטוח', r'insurance', r'הראל', r'מגדל', r'כלל', r'הפניקס', r'מנורה'
        ],
        'bank_fees': [
            r'עמלה', r'commission', r'fee', r'דמי ניהול', r'ריבית'
        ],
        'credit_card': [
            r'ויזה', r'visa', r'מסטרקארד', r'mastercard', r'ישראכרט',
            r'לאומי קארד', r'כאל', r'מקס', r'isracard', r'cal', r'max'
        ],
        'transfer': [
            r'העברה', r'transfer', r'הפקדה', r'deposit', r'משיכה', r'withdrawal'
        ],
        'loan': [
            r'הלוואה', r'loan', r'משכנתא', r'mortgage', r'החזר', r'repayment'
        ],
        'investment': [
            r'קרן נאמנות', r'fund', r'מניות', r'stocks', r'אג"ח', r'bonds',
            r'דיבידנד', r'dividend'
        ]
    }
    
    @classmethod
    def parse_csv(
        cls,
        content: Union[str, bytes],
        bank_format: BankFormat = BankFormat.AUTO,
        encoding: str = 'utf-8'
    ) -> List[BankTransaction]:
        """
        קליטת קובץ CSV
        Parse CSV bank statement
        """
        if isinstance(content, bytes):
            # נסיון לזהות קידוד
            for enc in ['utf-8', 'windows-1255', 'iso-8859-8', 'cp1252']:
                try:
                    content = content.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
        
        if bank_format == BankFormat.AUTO:
            bank_format = cls._detect_format(content)
        
        parser_map = {
            BankFormat.LEUMI: cls._parse_leumi,
            BankFormat.HAPOALIM: cls._parse_hapoalim,
            BankFormat.DISCOUNT: cls._parse_discount,
            BankFormat.MIZRAHI: cls._parse_mizrahi,
            BankFormat.ISRACARD: cls._parse_isracard,
            BankFormat.CAL: cls._parse_cal,
            BankFormat.MAX: cls._parse_max,
            BankFormat.GENERIC: cls._parse_generic
        }
        
        parser = parser_map.get(bank_format, cls._parse_generic)
        return parser(content)
    
    @classmethod
    def parse_excel(
        cls,
        content: bytes,
        bank_format: BankFormat = BankFormat.AUTO
    ) -> List[BankTransaction]:
        """
        קליטת קובץ Excel
        Parse Excel bank statement
        """
        try:
            import openpyxl
            from io import BytesIO
            
            wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
            ws = wb.active
            
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([str(cell) if cell else '' for cell in row])
            
            # המרה לפורמט CSV לעיבוד
            csv_content = '\n'.join([','.join(row) for row in rows])
            return cls.parse_csv(csv_content, bank_format)
            
        except ImportError:
            logger.error("openpyxl not installed for Excel parsing")
            raise ValueError("Excel parsing requires openpyxl library")
    
    @classmethod
    def _detect_format(cls, content: str) -> BankFormat:
        """זיהוי אוטומטי של פורמט הבנק"""
        content_lower = content.lower()
        
        if 'leumi' in content_lower or 'לאומי' in content:
            return BankFormat.LEUMI
        elif 'hapoalim' in content_lower or 'הפועלים' in content:
            return BankFormat.HAPOALIM
        elif 'discount' in content_lower or 'דיסקונט' in content:
            return BankFormat.DISCOUNT
        elif 'mizrahi' in content_lower or 'מזרחי' in content:
            return BankFormat.MIZRAHI
        elif 'isracard' in content_lower or 'ישראכרט' in content:
            return BankFormat.ISRACARD
        elif 'cal' in content_lower or 'כאל' in content:
            return BankFormat.CAL
        elif 'max' in content_lower or 'מקס' in content:
            return BankFormat.MAX
        
        return BankFormat.GENERIC
    
    @classmethod
    def _parse_date(cls, date_str: str) -> Optional[date]:
        """ניתוח תאריך"""
        if not date_str:
            return None
        
        date_str = date_str.strip()
        
        for fmt in cls.DATE_FORMATS:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        return None
    
    @classmethod
    def _parse_amount(cls, amount_str: str) -> Tuple[Decimal, bool]:
        """
        ניתוח סכום - מחזיר (סכום, האם חובה)
        """
        if not amount_str:
            return Decimal("0"), False
        
        # ניקוי הסכום
        amount_str = amount_str.strip()
        is_debit = False
        
        # זיהוי חובה
        if amount_str.startswith('-') or amount_str.startswith('(') or 'ח' in amount_str:
            is_debit = True
        
        # הסרת תווים לא רלוונטיים
        cleaned = re.sub(r'[^\d.,\-]', '', amount_str)
        cleaned = cleaned.replace(',', '')
        cleaned = cleaned.lstrip('-')
        
        try:
            amount = Decimal(cleaned) if cleaned else Decimal("0")
            if is_debit:
                amount = -amount
            return amount, is_debit
        except InvalidOperation:
            return Decimal("0"), False
    
    @classmethod
    def _categorize(cls, description: str) -> str:
        """קטגוריזציה על פי תיאור"""
        description_lower = description.lower()
        
        for category, patterns in cls.CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, description_lower, re.IGNORECASE):
                    return category
        
        return 'other'
    
    @classmethod
    def _parse_leumi(cls, content: str) -> List[BankTransaction]:
        """ניתוח דף בנק לאומי"""
        transactions = []
        reader = csv.reader(io.StringIO(content))
        
        header_found = False
        date_col, desc_col, debit_col, credit_col, balance_col = 0, 1, 2, 3, 4
        
        for row in reader:
            if not row:
                continue
            
            # חיפוש שורת כותרת
            if not header_found:
                row_lower = [str(cell).lower() for cell in row]
                if 'תאריך' in row_lower or 'date' in row_lower:
                    header_found = True
                    # מציאת אינדקסים
                    for i, cell in enumerate(row_lower):
                        if 'תאריך' in cell or 'date' in cell:
                            date_col = i
                        elif 'פרטים' in cell or 'תיאור' in cell or 'description' in cell:
                            desc_col = i
                        elif 'חובה' in cell or 'debit' in cell:
                            debit_col = i
                        elif 'זכות' in cell or 'credit' in cell:
                            credit_col = i
                        elif 'יתרה' in cell or 'balance' in cell:
                            balance_col = i
                continue
            
            try:
                tx_date = cls._parse_date(row[date_col] if len(row) > date_col else '')
                if not tx_date:
                    continue
                
                description = row[desc_col] if len(row) > desc_col else ''
                
                # חישוב סכום
                debit_amount, _ = cls._parse_amount(row[debit_col] if len(row) > debit_col else '')
                credit_amount, _ = cls._parse_amount(row[credit_col] if len(row) > credit_col else '')
                
                if debit_amount:
                    amount = -abs(debit_amount)
                    is_debit = True
                elif credit_amount:
                    amount = abs(credit_amount)
                    is_debit = False
                else:
                    continue
                
                balance, _ = cls._parse_amount(row[balance_col] if len(row) > balance_col else '')
                
                transactions.append(BankTransaction(
                    date=tx_date,
                    description=description,
                    amount=amount,
                    balance=balance if balance else None,
                    is_debit=is_debit,
                    category=cls._categorize(description)
                ))
                
            except (IndexError, ValueError) as e:
                logger.warning(f"Failed to parse row: {row}, error: {e}")
                continue
        
        return transactions
    
    @classmethod
    def _parse_hapoalim(cls, content: str) -> List[BankTransaction]:
        """ניתוח דף בנק הפועלים"""
        return cls._parse_generic(content)  # דומה לפורמט גנרי
    
    @classmethod
    def _parse_discount(cls, content: str) -> List[BankTransaction]:
        """ניתוח דף בנק דיסקונט"""
        return cls._parse_generic(content)
    
    @classmethod
    def _parse_mizrahi(cls, content: str) -> List[BankTransaction]:
        """ניתוח דף בנק מזרחי-טפחות"""
        return cls._parse_generic(content)
    
    @classmethod
    def _parse_isracard(cls, content: str) -> List[BankTransaction]:
        """ניתוח דף כרטיס אשראי ישראכרט"""
        transactions = []
        reader = csv.reader(io.StringIO(content))
        
        header_found = False
        
        for row in reader:
            if not row:
                continue
            
            row_str = ','.join(row).lower()
            if not header_found:
                if 'תאריך' in row_str or 'date' in row_str:
                    header_found = True
                continue
            
            try:
                # פורמט טיפוסי של ישראכרט
                if len(row) >= 4:
                    tx_date = cls._parse_date(row[0])
                    if not tx_date:
                        continue
                    
                    description = row[1]
                    amount, is_debit = cls._parse_amount(row[2] if len(row) > 2 else row[3])
                    
                    transactions.append(BankTransaction(
                        date=tx_date,
                        description=description,
                        amount=amount,
                        is_debit=is_debit,
                        category=cls._categorize(description),
                        transaction_type='credit_card'
                    ))
                    
            except (IndexError, ValueError) as e:
                logger.warning(f"Failed to parse isracard row: {row}, error: {e}")
                continue
        
        return transactions
    
    @classmethod
    def _parse_cal(cls, content: str) -> List[BankTransaction]:
        """ניתוח דף כרטיס אשראי כאל"""
        return cls._parse_isracard(content)  # דומה לישראכרט
    
    @classmethod
    def _parse_max(cls, content: str) -> List[BankTransaction]:
        """ניתוח דף כרטיס אשראי max"""
        return cls._parse_isracard(content)
    
    @classmethod
    def _parse_generic(cls, content: str) -> List[BankTransaction]:
        """
        ניתוח גנרי - מנסה לזהות אוטומטית את המבנה
        Generic parser - attempts to auto-detect structure
        """
        transactions = []
        
        # ניסיון עם CSV
        try:
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
        except:
            # ניסיון עם טאב
            rows = [line.split('\t') for line in content.split('\n')]
        
        if not rows:
            return []
        
        # מציאת שורת כותרת
        header_row = -1
        for i, row in enumerate(rows):
            row_str = ','.join(row).lower()
            if 'תאריך' in row_str or 'date' in row_str:
                header_row = i
                break
        
        if header_row == -1:
            header_row = 0
        
        # זיהוי עמודות
        header = [str(cell).lower() for cell in rows[header_row]] if rows else []
        
        date_col = None
        desc_col = None
        amount_col = None
        debit_col = None
        credit_col = None
        balance_col = None
        
        for i, cell in enumerate(header):
            if 'תאריך' in cell or 'date' in cell:
                date_col = i
            elif 'תיאור' in cell or 'פרטים' in cell or 'description' in cell:
                desc_col = i
            elif 'סכום' in cell or 'amount' in cell:
                amount_col = i
            elif 'חובה' in cell or 'debit' in cell:
                debit_col = i
            elif 'זכות' in cell or 'credit' in cell:
                credit_col = i
            elif 'יתרה' in cell or 'balance' in cell:
                balance_col = i
        
        # ברירות מחדל
        if date_col is None:
            date_col = 0
        if desc_col is None:
            desc_col = 1
        if amount_col is None and debit_col is None:
            amount_col = 2
        
        # עיבוד שורות
        for row in rows[header_row + 1:]:
            if not row or all(not cell.strip() for cell in row):
                continue
            
            try:
                tx_date = cls._parse_date(row[date_col] if len(row) > date_col else '')
                if not tx_date:
                    continue
                
                description = row[desc_col] if len(row) > desc_col else ''
                
                # חישוב סכום
                if debit_col is not None and credit_col is not None:
                    debit_amount, _ = cls._parse_amount(row[debit_col] if len(row) > debit_col else '')
                    credit_amount, _ = cls._parse_amount(row[credit_col] if len(row) > credit_col else '')
                    
                    if debit_amount:
                        amount = -abs(debit_amount)
                        is_debit = True
                    elif credit_amount:
                        amount = abs(credit_amount)
                        is_debit = False
                    else:
                        continue
                else:
                    amount, is_debit = cls._parse_amount(
                        row[amount_col] if len(row) > amount_col else ''
                    )
                
                if amount == Decimal("0"):
                    continue
                
                balance = None
                if balance_col is not None and len(row) > balance_col:
                    balance, _ = cls._parse_amount(row[balance_col])
                
                transactions.append(BankTransaction(
                    date=tx_date,
                    description=description,
                    amount=amount,
                    balance=balance if balance else None,
                    is_debit=is_debit,
                    category=cls._categorize(description)
                ))
                
            except (IndexError, ValueError) as e:
                logger.warning(f"Failed to parse generic row: {row}, error: {e}")
                continue
        
        return transactions


class BankStatementService:
    """
    שירות קליטת וניתוח דפי בנק
    Bank statement import and analysis service
    """
    
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id
        self.parser = BankStatementParser()
    
    def import_statement(
        self,
        content: Union[str, bytes],
        bank_format: BankFormat = BankFormat.AUTO,
        file_type: str = 'csv',
        account_id: Optional[int] = None,
        auto_categorize: bool = True,
        create_transactions: bool = True
    ) -> Dict[str, Any]:
        """
        ייבוא דף בנק
        Import bank statement and optionally create transactions
        """
        # קליטת העסקאות
        if file_type == 'excel' or file_type == 'xlsx':
            transactions = self.parser.parse_excel(content, bank_format)
        else:
            transactions = self.parser.parse_csv(content, bank_format)
        
        if not transactions:
            return {
                'success': False,
                'error': 'No transactions found in file',
                'transactions': []
            }
        
        # ניתוח וסיכום
        analysis = self._analyze_transactions(transactions)
        
        # יצירת עסקאות במסד הנתונים
        created_count = 0
        duplicates_count = 0
        
        if create_transactions:
            # מציאת או יצירת חשבון בנק
            if not account_id:
                account = self._get_or_create_bank_account()
                account_id = account.id
            
            for tx in transactions:
                # בדיקת כפילות
                existing = self._check_duplicate(tx)
                if existing:
                    duplicates_count += 1
                    continue
                
                # יצירת עסקה
                db_transaction = Transaction(
                    organization_id=self.organization_id,
                    account_id=account_id,
                    transaction_type=TransactionType.EXPENSE if tx.is_debit else TransactionType.INCOME,
                    amount=abs(tx.amount),
                    description=tx.description,
                    category=tx.category if auto_categorize else 'uncategorized',
                    transaction_date=datetime.combine(tx.date, datetime.min.time()),
                    external_id=f"bank_{tx.date}_{hash(tx.description)}_{tx.amount}"
                )
                
                self.db.add(db_transaction)
                created_count += 1
            
            self.db.commit()
        
        return {
            'success': True,
            'parsed_transactions': len(transactions),
            'created_transactions': created_count,
            'duplicates_skipped': duplicates_count,
            'analysis': analysis,
            'transactions': [tx.to_dict() for tx in transactions]
        }
    
    def _analyze_transactions(
        self,
        transactions: List[BankTransaction]
    ) -> Dict[str, Any]:
        """ניתוח עסקאות"""
        if not transactions:
            return {}
        
        # חישובים בסיסיים
        total_income = sum(tx.amount for tx in transactions if not tx.is_debit)
        total_expenses = sum(abs(tx.amount) for tx in transactions if tx.is_debit)
        net_flow = total_income - total_expenses
        
        # קטגוריות
        category_breakdown = {}
        for tx in transactions:
            cat = tx.category or 'other'
            if cat not in category_breakdown:
                category_breakdown[cat] = {'count': 0, 'total': Decimal("0")}
            category_breakdown[cat]['count'] += 1
            category_breakdown[cat]['total'] += abs(tx.amount)
        
        # המרה לפורמט JSON-friendly
        for cat in category_breakdown:
            category_breakdown[cat]['total'] = float(category_breakdown[cat]['total'])
        
        # טווח תאריכים
        dates = [tx.date for tx in transactions]
        
        # ממוצעים
        avg_income = total_income / len([tx for tx in transactions if not tx.is_debit]) if any(not tx.is_debit for tx in transactions) else 0
        avg_expense = total_expenses / len([tx for tx in transactions if tx.is_debit]) if any(tx.is_debit for tx in transactions) else 0
        
        return {
            'total_transactions': len(transactions),
            'total_income': float(total_income),
            'total_expenses': float(total_expenses),
            'net_flow': float(net_flow),
            'average_income': float(avg_income),
            'average_expense': float(avg_expense),
            'date_range': {
                'start': min(dates).isoformat(),
                'end': max(dates).isoformat()
            },
            'category_breakdown': category_breakdown,
            'income_transactions': len([tx for tx in transactions if not tx.is_debit]),
            'expense_transactions': len([tx for tx in transactions if tx.is_debit])
        }
    
    def _get_or_create_bank_account(self) -> Account:
        """מציאת או יצירת חשבון בנק"""
        account = self.db.query(Account).filter(
            Account.organization_id == self.organization_id,
            Account.account_type == AccountType.ASSET,
            Account.name.like('%בנק%')
        ).first()
        
        if not account:
            account = Account(
                organization_id=self.organization_id,
                name='חשבון בנק',
                account_type=AccountType.ASSET,
                balance=Decimal("0"),
                currency="ILS"
            )
            self.db.add(account)
            self.db.commit()
            self.db.refresh(account)
        
        return account
    
    def _check_duplicate(self, tx: BankTransaction) -> bool:
        """בדיקת עסקה כפולה"""
        existing = self.db.query(Transaction).filter(
            Transaction.organization_id == self.organization_id,
            Transaction.transaction_date == datetime.combine(tx.date, datetime.min.time()),
            Transaction.amount == abs(tx.amount),
            Transaction.description == tx.description
        ).first()
        
        return existing is not None
    
    def get_spending_patterns(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        ניתוח דפוסי הוצאות
        Analyze spending patterns from imported transactions
        """
        query = self.db.query(Transaction).filter(
            Transaction.organization_id == self.organization_id,
            Transaction.transaction_type == TransactionType.EXPENSE
        )
        
        if from_date:
            query = query.filter(Transaction.transaction_date >= from_date)
        if to_date:
            query = query.filter(Transaction.transaction_date <= to_date)
        
        transactions = query.all()
        
        if not transactions:
            return {'patterns': [], 'message': 'No expense transactions found'}
        
        # ניתוח לפי קטגוריה
        category_stats = {}
        for tx in transactions:
            cat = tx.category or 'other'
            if cat not in category_stats:
                category_stats[cat] = {
                    'total': Decimal("0"),
                    'count': 0,
                    'transactions': []
                }
            category_stats[cat]['total'] += tx.amount
            category_stats[cat]['count'] += 1
            category_stats[cat]['transactions'].append({
                'date': tx.transaction_date.date().isoformat(),
                'amount': float(tx.amount),
                'description': tx.description
            })
        
        # חישוב אחוזים
        total_spending = sum(s['total'] for s in category_stats.values())
        
        patterns = []
        for cat, stats in category_stats.items():
            patterns.append({
                'category': cat,
                'total': float(stats['total']),
                'count': stats['count'],
                'percentage': float(stats['total'] / total_spending * 100) if total_spending else 0,
                'average': float(stats['total'] / stats['count']) if stats['count'] else 0
            })
        
        # מיון לפי סך הכל
        patterns.sort(key=lambda x: x['total'], reverse=True)
        
        return {
            'patterns': patterns,
            'total_spending': float(total_spending),
            'transaction_count': len(transactions),
            'category_count': len(patterns)
        }
    
    def detect_recurring_transactions(self) -> List[Dict[str, Any]]:
        """
        זיהוי עסקאות חוזרות
        Detect recurring transactions from bank statements
        """
        transactions = self.db.query(Transaction).filter(
            Transaction.organization_id == self.organization_id
        ).order_by(Transaction.transaction_date).all()
        
        # קיבוץ לפי תיאור וסכום דומים
        grouped = {}
        for tx in transactions:
            # נורמליזציה של התיאור
            desc_key = re.sub(r'\d+', '#', tx.description.lower().strip())
            amount_key = round(float(tx.amount), 0)
            
            key = f"{desc_key}_{amount_key}"
            
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(tx)
        
        # זיהוי עסקאות חוזרות (לפחות 2 מופעים)
        recurring = []
        for key, txs in grouped.items():
            if len(txs) >= 2:
                dates = [tx.transaction_date for tx in txs]
                
                # חישוב מרווח ממוצע
                intervals = []
                for i in range(1, len(dates)):
                    interval = (dates[i] - dates[i-1]).days
                    intervals.append(interval)
                
                avg_interval = sum(intervals) / len(intervals) if intervals else 0
                
                # קביעת תדירות
                if 25 <= avg_interval <= 35:
                    frequency = 'monthly'
                elif 7 <= avg_interval <= 10:
                    frequency = 'weekly'
                elif 350 <= avg_interval <= 380:
                    frequency = 'yearly'
                else:
                    frequency = 'irregular'
                
                recurring.append({
                    'description': txs[0].description,
                    'amount': float(txs[0].amount),
                    'occurrences': len(txs),
                    'frequency': frequency,
                    'average_interval_days': round(avg_interval, 1),
                    'last_occurrence': max(dates).isoformat(),
                    'category': txs[0].category
                })
        
        # מיון לפי מספר מופעים
        recurring.sort(key=lambda x: x['occurrences'], reverse=True)
        
        return recurring
