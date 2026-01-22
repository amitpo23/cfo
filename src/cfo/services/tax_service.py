"""
Tax & Compliance Service
שירות מס ורגולציה
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..models import Transaction, Account
from ..database import SessionLocal


class TaxType(str, Enum):
    """סוג מס"""
    VAT = "vat"                    # מע"מ
    INCOME_TAX = "income_tax"      # מס הכנסה
    WITHHOLDING = "withholding"    # ניכוי במקור
    SOCIAL_SECURITY = "social_security"  # ביטוח לאומי
    HEALTH_TAX = "health_tax"      # מס בריאות
    PROPERTY_TAX = "property_tax"  # ארנונה


class ReportType(str, Enum):
    """סוג דיווח"""
    VAT_REPORT = "vat_report"          # דוח מע"מ
    ANNUAL_REPORT = "annual_report"    # דוח שנתי
    REPORT_856 = "856"                 # ניכויים מתשלומים לתושב חוץ
    REPORT_126 = "126"                 # דוח שנתי ניכויים
    REPORT_102 = "102"                 # דוח חודשי מעסיק
    REPORT_6111 = "6111"               # דוח שנתי מקוון


class ComplianceStatus(str, Enum):
    """סטטוס ציות"""
    COMPLIANT = "compliant"
    PENDING = "pending"
    OVERDUE = "overdue"
    WARNING = "warning"


@dataclass
class VATReport:
    """דוח מע"מ"""
    period: str
    period_start: str
    period_end: str
    due_date: str
    # עסקאות
    sales_taxable: float
    sales_exempt: float
    sales_zero_rated: float
    total_sales: float
    output_vat: float
    # תשומות
    purchases_taxable: float
    purchases_exempt: float
    input_vat: float
    input_vat_fixed_assets: float
    total_input_vat: float
    # סיכום
    vat_payable: float
    vat_refund: float
    net_vat: float
    status: str
    # פירוט
    transactions: List[Dict]


@dataclass
class TaxAdvancePayment:
    """מקדמת מס"""
    tax_type: TaxType
    period: str
    due_date: str
    calculated_amount: float
    previous_payments: float
    remaining_amount: float
    payment_status: str
    calculation_basis: str
    notes: str


@dataclass
class WithholdingReport:
    """דוח ניכויים"""
    period: str
    report_type: ReportType
    # ניכויי עובדים
    employee_tax: float
    employee_social_security: float
    employee_health: float
    employer_social_security: float
    # ניכויי ספקים
    supplier_withholding: float
    contractor_withholding: float
    # סיכום
    total_withholding: float
    total_employer_cost: float
    due_date: str
    status: str
    employees: List[Dict]
    suppliers: List[Dict]


@dataclass
class TaxCalendar:
    """לוח זמנים מס"""
    upcoming_deadlines: List[Dict]
    overdue_items: List[Dict]
    completed_items: List[Dict]
    total_upcoming_payments: float


@dataclass
class TaxPlanningSuggestion:
    """הצעת תכנון מס"""
    suggestion_id: str
    category: str
    title: str
    description: str
    potential_savings: float
    implementation_effort: str
    deadline: Optional[str]
    priority: str


@dataclass
class ComplianceReport:
    """דוח ציות"""
    report_date: str
    overall_status: ComplianceStatus
    compliance_score: int
    items: List[Dict]
    risks: List[Dict]
    recommendations: List[str]


# שיעורי מס בישראל (2024)
TAX_RATES = {
    'vat': 0.17,  # 17% מע"מ
    'corporate_tax': 0.23,  # 23% מס חברות
    'withholding_supplier': 0.30,  # 30% ניכוי ספקים (ללא אישור)
    'withholding_contractor': 0.20,  # 20% ניכוי קבלנים
    'social_security_employee': 0.12,  # ביטוח לאומי עובד (משוקלל)
    'social_security_employer': 0.0755,  # ביטוח לאומי מעביד
    'health_tax': 0.05,  # מס בריאות
}

# מדרגות מס הכנסה 2024
INCOME_TAX_BRACKETS = [
    (7010, 0.10),
    (10060, 0.14),
    (16150, 0.20),
    (22440, 0.31),
    (46690, 0.35),
    (float('inf'), 0.47)
]


class TaxComplianceService:
    """
    שירות מס ורגולציה
    Tax & Compliance Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        
        # הגדרות חברה
        self.company_vat_number = '123456789'
        self.reporting_frequency = 'monthly'  # או bi-monthly
    
    def generate_vat_report(
        self,
        year: int,
        month: int
    ) -> VATReport:
        """
        הפקת דוח מע"מ
        Generate VAT Report
        """
        # תאריכים
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # תאריך הגשה - 15 לחודש העוקב
        if month == 12:
            due_date = date(year + 1, 1, 15)
        else:
            due_date = date(year, month + 1, 15)
        
        # שליפת עסקאות
        transactions = self._get_vat_transactions(start_date, end_date)
        
        # סיכום מכירות
        sales_taxable = sum(t['amount'] for t in transactions if t['type'] == 'sale' and t['vat_type'] == 'taxable')
        sales_exempt = sum(t['amount'] for t in transactions if t['type'] == 'sale' and t['vat_type'] == 'exempt')
        sales_zero = sum(t['amount'] for t in transactions if t['type'] == 'sale' and t['vat_type'] == 'zero')
        total_sales = sales_taxable + sales_exempt + sales_zero
        output_vat = sales_taxable * TAX_RATES['vat']
        
        # סיכום רכישות
        purchases_taxable = sum(t['amount'] for t in transactions if t['type'] == 'purchase' and t['vat_type'] == 'taxable')
        purchases_exempt = sum(t['amount'] for t in transactions if t['type'] == 'purchase' and t['vat_type'] == 'exempt')
        input_vat = sum(t['vat_amount'] for t in transactions if t['type'] == 'purchase' and t['vat_type'] == 'taxable')
        input_vat_fixed = sum(t['vat_amount'] for t in transactions if t['type'] == 'purchase' and t.get('is_fixed_asset'))
        
        # חישוב מע"מ
        total_input = input_vat + input_vat_fixed
        vat_payable = output_vat - total_input
        
        status = 'pending'
        if date.today() > due_date:
            status = 'overdue'
        elif vat_payable < 0:
            status = 'refund_due'
        
        return VATReport(
            period=f"{year}-{month:02d}",
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            due_date=due_date.isoformat(),
            sales_taxable=sales_taxable,
            sales_exempt=sales_exempt,
            sales_zero_rated=sales_zero,
            total_sales=total_sales,
            output_vat=output_vat,
            purchases_taxable=purchases_taxable,
            purchases_exempt=purchases_exempt,
            input_vat=input_vat,
            input_vat_fixed_assets=input_vat_fixed,
            total_input_vat=total_input,
            vat_payable=max(0, vat_payable),
            vat_refund=max(0, -vat_payable),
            net_vat=vat_payable,
            status=status,
            transactions=transactions
        )
    
    def calculate_tax_advance(
        self,
        year: int,
        month: int,
        tax_type: TaxType = TaxType.INCOME_TAX
    ) -> TaxAdvancePayment:
        """
        חישוב מקדמות מס
        Calculate Tax Advance Payment
        """
        # נתונים היסטוריים
        annual_profit = self._get_annual_profit_estimate(year)
        monthly_advance = annual_profit * TAX_RATES['corporate_tax'] / 12
        
        # תשלומים קודמים
        previous = self._get_previous_payments(year, month, tax_type)
        
        # תאריך תשלום - 15 לחודש
        due_date = date(year, month, 15)
        
        status = 'pending'
        if date.today() > due_date and monthly_advance > 0:
            status = 'overdue'
        elif previous >= monthly_advance:
            status = 'paid'
        
        return TaxAdvancePayment(
            tax_type=tax_type,
            period=f"{year}-{month:02d}",
            due_date=due_date.isoformat(),
            calculated_amount=monthly_advance,
            previous_payments=previous,
            remaining_amount=max(0, monthly_advance - previous),
            payment_status=status,
            calculation_basis=f"רווח שנתי משוער: ₪{annual_profit:,.0f} × 23% ÷ 12",
            notes="מבוסס על רווח שנה קודמת + התאמות"
        )
    
    def generate_withholding_report(
        self,
        year: int,
        month: int,
        report_type: ReportType = ReportType.REPORT_102
    ) -> WithholdingReport:
        """
        הפקת דוח ניכויים
        Generate Withholding Report
        """
        # נתוני עובדים
        employees = self._get_employee_data(year, month)
        
        employee_tax = sum(e['income_tax'] for e in employees)
        employee_ss = sum(e['social_security_employee'] for e in employees)
        employee_health = sum(e['health_tax'] for e in employees)
        employer_ss = sum(e['social_security_employer'] for e in employees)
        
        # נתוני ספקים
        suppliers = self._get_supplier_withholding(year, month)
        supplier_wh = sum(s['withholding'] for s in suppliers if s['type'] == 'supplier')
        contractor_wh = sum(s['withholding'] for s in suppliers if s['type'] == 'contractor')
        
        total_withholding = employee_tax + employee_ss + employee_health + supplier_wh + contractor_wh
        total_employer = employer_ss
        
        # תאריך הגשה
        due_date = date(year, month + 1 if month < 12 else 1, 15)
        if month == 12:
            due_date = date(year + 1, 1, 15)
        
        status = 'pending' if date.today() <= due_date else 'overdue'
        
        return WithholdingReport(
            period=f"{year}-{month:02d}",
            report_type=report_type,
            employee_tax=employee_tax,
            employee_social_security=employee_ss,
            employee_health=employee_health,
            employer_social_security=employer_ss,
            supplier_withholding=supplier_wh,
            contractor_withholding=contractor_wh,
            total_withholding=total_withholding,
            total_employer_cost=total_employer,
            due_date=due_date.isoformat(),
            status=status,
            employees=employees,
            suppliers=suppliers
        )
    
    def get_tax_calendar(
        self,
        months_ahead: int = 3
    ) -> TaxCalendar:
        """
        לוח זמנים מס
        Tax Calendar
        """
        today = date.today()
        end_date = today + timedelta(days=months_ahead * 30)
        
        upcoming = []
        overdue = []
        completed = []
        
        # מע"מ חודשי
        for m in range(months_ahead + 1):
            month_date = today + timedelta(days=m * 30)
            due = date(month_date.year, month_date.month, 15)
            
            item = {
                'type': 'VAT',
                'type_hebrew': 'דוח מע"מ',
                'period': f"{month_date.year}-{month_date.month:02d}",
                'due_date': due.isoformat(),
                'estimated_amount': 15000,  # הערכה
                'status': 'pending'
            }
            
            if due < today:
                overdue.append(item)
            elif due <= end_date:
                upcoming.append(item)
        
        # מקדמות מס
        for m in range(months_ahead + 1):
            month_date = today + timedelta(days=m * 30)
            due = date(month_date.year, month_date.month, 15)
            
            item = {
                'type': 'TAX_ADVANCE',
                'type_hebrew': 'מקדמות מס',
                'period': f"{month_date.year}-{month_date.month:02d}",
                'due_date': due.isoformat(),
                'estimated_amount': 8000,
                'status': 'pending'
            }
            
            if due < today:
                overdue.append(item)
            elif due <= end_date:
                upcoming.append(item)
        
        # ניכויים (102)
        for m in range(months_ahead + 1):
            month_date = today + timedelta(days=m * 30)
            due = date(month_date.year, month_date.month, 15)
            
            item = {
                'type': 'WITHHOLDING_102',
                'type_hebrew': 'דוח 102 - ניכויים',
                'period': f"{month_date.year}-{month_date.month:02d}",
                'due_date': due.isoformat(),
                'estimated_amount': 25000,
                'status': 'pending'
            }
            
            if due < today:
                overdue.append(item)
            elif due <= end_date:
                upcoming.append(item)
        
        # מיון לפי תאריך
        upcoming.sort(key=lambda x: x['due_date'])
        overdue.sort(key=lambda x: x['due_date'])
        
        total_upcoming = sum(item['estimated_amount'] for item in upcoming)
        
        return TaxCalendar(
            upcoming_deadlines=upcoming,
            overdue_items=overdue,
            completed_items=completed,
            total_upcoming_payments=total_upcoming
        )
    
    def get_tax_planning_suggestions(self) -> List[TaxPlanningSuggestion]:
        """
        הצעות לתכנון מס
        Tax Planning Suggestions
        """
        suggestions = []
        today = date.today()
        
        # הפקדות לקופות גמל
        suggestions.append(TaxPlanningSuggestion(
            suggestion_id='TP001',
            category='פנסיה',
            title='הגדלת הפרשות לפנסיה',
            description='הגדלת הפרשות מעביד לקרן פנסיה מעבר למינימום מאפשרת הטבת מס',
            potential_savings=5000,
            implementation_effort='low',
            deadline=f"{today.year}-12-31",
            priority='high'
        ))
        
        # קרן השתלמות
        suggestions.append(TaxPlanningSuggestion(
            suggestion_id='TP002',
            category='חיסכון',
            title='מקסום הפקדה לקרן השתלמות',
            description='הפקדה עד 7.5% מהשכר/רווח לקרן השתלמות פטורה ממס',
            potential_savings=8000,
            implementation_effort='low',
            deadline=f"{today.year}-12-31",
            priority='high'
        ))
        
        # פחת מואץ
        suggestions.append(TaxPlanningSuggestion(
            suggestion_id='TP003',
            category='השקעות',
            title='רכישת ציוד לפני סוף שנה',
            description='רכישת ציוד לפני סוף שנת המס מאפשרת ניכוי פחת מואץ',
            potential_savings=12000,
            implementation_effort='medium',
            deadline=f"{today.year}-12-31",
            priority='medium'
        ))
        
        # הוצאות מו"פ
        suggestions.append(TaxPlanningSuggestion(
            suggestion_id='TP004',
            category='מו"פ',
            title='ניצול הטבות מו"פ',
            description='הוצאות מחקר ופיתוח זכאיות לניכוי מוגדל של 200%',
            potential_savings=20000,
            implementation_effort='high',
            deadline=None,
            priority='medium'
        ))
        
        # תכנון מע"מ
        suggestions.append(TaxPlanningSuggestion(
            suggestion_id='TP005',
            category='מע"מ',
            title='תזמון רכישות גדולות',
            description='רכישות גדולות עם מע"מ בתחילת חודש משפרות תזרים (מע"מ תשומות מוקדם)',
            potential_savings=3000,
            implementation_effort='low',
            deadline=None,
            priority='low'
        ))
        
        return suggestions
    
    def get_compliance_report(self) -> ComplianceReport:
        """
        דוח ציות רגולטורי
        Compliance Report
        """
        today = date.today()
        
        items = []
        risks = []
        
        # בדיקת דוחות מע"מ
        for m in range(3):
            month = today.month - m - 1
            year = today.year
            if month <= 0:
                month += 12
                year -= 1
            
            items.append({
                'item': f'דוח מע"מ {year}-{month:02d}',
                'status': 'completed' if m > 0 else 'pending',
                'due_date': date(year if month < 12 else year + 1, month + 1 if month < 12 else 1, 15).isoformat()
            })
        
        # בדיקת 102
        items.append({
            'item': f'דוח 102 {today.year}-{today.month - 1:02d}',
            'status': 'completed',
            'due_date': date(today.year, today.month, 15).isoformat()
        })
        
        # בדיקת מקדמות
        items.append({
            'item': f'מקדמות מס {today.year}-{today.month:02d}',
            'status': 'pending',
            'due_date': date(today.year, today.month, 15).isoformat()
        })
        
        # זיהוי סיכונים
        calendar = self.get_tax_calendar()
        if calendar.overdue_items:
            risks.append({
                'risk': 'דיווחים באיחור',
                'severity': 'high',
                'count': len(calendar.overdue_items),
                'impact': 'קנסות ועיצומים כספיים'
            })
        
        # חישוב ציון
        completed = len([i for i in items if i['status'] == 'completed'])
        total = len(items)
        score = int((completed / total) * 100) if total else 100
        
        # סטטוס כללי
        if score >= 90 and not risks:
            overall = ComplianceStatus.COMPLIANT
        elif score >= 70:
            overall = ComplianceStatus.WARNING
        elif calendar.overdue_items:
            overall = ComplianceStatus.OVERDUE
        else:
            overall = ComplianceStatus.PENDING
        
        recommendations = []
        if score < 100:
            recommendations.append("להשלים דיווחים חסרים")
        if risks:
            recommendations.append("לטפל בדחיפות בפריטים באיחור")
        recommendations.append("להגדיר תזכורות אוטומטיות לדדליינים")
        
        return ComplianceReport(
            report_date=today.isoformat(),
            overall_status=overall,
            compliance_score=score,
            items=items,
            risks=risks,
            recommendations=recommendations
        )
    
    def export_vat_file(
        self,
        year: int,
        month: int,
        format: str = 'shaam'
    ) -> Dict:
        """
        ייצוא קובץ מע"מ לשע"מ
        Export VAT file for tax authority
        """
        report = self.generate_vat_report(year, month)
        
        if format == 'shaam':
            # פורמט שע"מ
            return {
                'filename': f'VAT_{self.company_vat_number}_{year}{month:02d}.txt',
                'format': 'SHAAM_VAT',
                'records': len(report.transactions),
                'total_sales': report.total_sales,
                'total_vat': report.output_vat,
                'content': self._format_shaam_file(report)
            }
        else:
            # XML
            return {
                'filename': f'VAT_{year}{month:02d}.xml',
                'format': 'XML',
                'content': self._format_xml_file(report)
            }
    
    def _get_vat_transactions(self, start_date: date, end_date: date) -> List[Dict]:
        """שליפת עסקאות למע"מ"""
        import random
        transactions = []
        
        # מכירות
        for i in range(15):
            transactions.append({
                'id': f'INV-{1000 + i}',
                'date': (start_date + timedelta(days=random.randint(0, 28))).isoformat(),
                'type': 'sale',
                'description': f'מכירה {i + 1}',
                'amount': random.randint(5000, 50000),
                'vat_amount': random.randint(850, 8500),
                'vat_type': random.choice(['taxable', 'taxable', 'taxable', 'exempt', 'zero']),
                'customer': f'לקוח {i + 1}'
            })
        
        # רכישות
        for i in range(10):
            amount = random.randint(2000, 30000)
            transactions.append({
                'id': f'PINV-{2000 + i}',
                'date': (start_date + timedelta(days=random.randint(0, 28))).isoformat(),
                'type': 'purchase',
                'description': f'רכישה {i + 1}',
                'amount': amount,
                'vat_amount': amount * 0.17,
                'vat_type': 'taxable',
                'is_fixed_asset': random.random() > 0.8,
                'supplier': f'ספק {i + 1}'
            })
        
        return transactions
    
    def _get_annual_profit_estimate(self, year: int) -> float:
        """הערכת רווח שנתי"""
        import random
        return random.randint(300000, 600000)
    
    def _get_previous_payments(self, year: int, month: int, tax_type: TaxType) -> float:
        """תשלומים קודמים"""
        return 0
    
    def _get_employee_data(self, year: int, month: int) -> List[Dict]:
        """נתוני עובדים"""
        import random
        employees = []
        
        for i in range(5):
            gross = random.randint(8000, 25000)
            employees.append({
                'id': f'EMP-{i + 1}',
                'name': f'עובד {i + 1}',
                'gross_salary': gross,
                'income_tax': gross * 0.15,
                'social_security_employee': gross * 0.12,
                'health_tax': gross * 0.05,
                'social_security_employer': gross * 0.0755,
                'net_salary': gross * 0.68
            })
        
        return employees
    
    def _get_supplier_withholding(self, year: int, month: int) -> List[Dict]:
        """ניכויי ספקים"""
        import random
        suppliers = []
        
        for i in range(3):
            amount = random.randint(5000, 20000)
            suppliers.append({
                'id': f'SUP-{i + 1}',
                'name': f'ספק {i + 1}',
                'type': random.choice(['supplier', 'contractor']),
                'gross_amount': amount,
                'withholding': amount * 0.3,
                'net_payment': amount * 0.7
            })
        
        return suppliers
    
    def _format_shaam_file(self, report: VATReport) -> str:
        """פורמט שע"מ"""
        lines = []
        lines.append(f"H|{self.company_vat_number}|{report.period}|{report.total_sales:.0f}|{report.output_vat:.0f}")
        
        for tx in report.transactions:
            lines.append(f"D|{tx['id']}|{tx['date']}|{tx['amount']:.0f}|{tx['vat_amount']:.0f}")
        
        lines.append(f"T|{len(report.transactions)}|{report.net_vat:.0f}")
        return '\n'.join(lines)
    
    def _format_xml_file(self, report: VATReport) -> str:
        """פורמט XML"""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<VATReport>
    <Period>{report.period}</Period>
    <CompanyVAT>{self.company_vat_number}</CompanyVAT>
    <TotalSales>{report.total_sales}</TotalSales>
    <OutputVAT>{report.output_vat}</OutputVAT>
    <InputVAT>{report.total_input_vat}</InputVAT>
    <NetVAT>{report.net_vat}</NetVAT>
</VATReport>"""
