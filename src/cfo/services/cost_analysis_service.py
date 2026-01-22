"""
Cost & Profitability Analysis Service
שירות ניתוח עלויות ורווחיות
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


class CostType(str, Enum):
    """סוג עלות"""
    DIRECT = "direct"        # עלות ישירה
    INDIRECT = "indirect"    # עלות עקיפה
    FIXED = "fixed"          # קבועה
    VARIABLE = "variable"    # משתנה


class ProfitabilityDimension(str, Enum):
    """מימד רווחיות"""
    PRODUCT = "product"
    SERVICE = "service"
    CUSTOMER = "customer"
    PROJECT = "project"
    DEPARTMENT = "department"
    REGION = "region"


@dataclass
class CostItem:
    """פריט עלות"""
    cost_id: str
    name: str
    name_hebrew: str
    cost_type: CostType
    amount: float
    percentage_of_total: float
    unit_cost: Optional[float]
    trend: str
    budget: Optional[float]
    variance: Optional[float]


@dataclass
class CostBreakdown:
    """פירוט עלויות"""
    period: str
    total_costs: float
    direct_costs: float
    indirect_costs: float
    fixed_costs: float
    variable_costs: float
    cost_items: List[CostItem]
    cost_per_unit: float
    cost_trends: List[Dict]


@dataclass
class ProfitabilityItem:
    """פריט רווחיות"""
    item_id: str
    name: str
    dimension: ProfitabilityDimension
    revenue: float
    direct_costs: float
    gross_profit: float
    gross_margin: float
    allocated_overhead: float
    net_profit: float
    net_margin: float
    roi: float
    rank: int
    recommendations: List[str]


@dataclass
class ProfitabilityAnalysis:
    """ניתוח רווחיות"""
    analysis_date: str
    dimension: ProfitabilityDimension
    total_revenue: float
    total_costs: float
    total_profit: float
    average_margin: float
    items: List[ProfitabilityItem]
    top_performers: List[str]
    underperformers: List[str]
    insights: List[str]


@dataclass
class ProductCost:
    """עלות מוצר"""
    product_id: str
    product_name: str
    selling_price: float
    material_cost: float
    labor_cost: float
    overhead_cost: float
    total_cost: float
    gross_profit: float
    gross_margin: float
    contribution_margin: float
    break_even_units: int
    current_volume: int
    is_profitable: bool


@dataclass
class COGSAnalysis:
    """ניתוח עלות המכר"""
    period: str
    total_cogs: float
    cogs_percentage: float
    components: List[Dict]
    trends: List[Dict]
    by_category: Dict[str, float]
    optimization_opportunities: List[str]


class CostAnalysisService:
    """
    שירות ניתוח עלויות ורווחיות
    Cost & Profitability Analysis Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        
        # יחסי הקצאה
        self.overhead_allocation_rate = 0.15  # 15% overhead
    
    def get_cost_breakdown(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> CostBreakdown:
        """
        פירוט עלויות
        Cost Breakdown
        """
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = date(end_date.year, end_date.month, 1)
        
        # שליפת עלויות
        costs = self._get_costs(start_date, end_date)
        
        total = sum(c['amount'] for c in costs)
        direct = sum(c['amount'] for c in costs if c['type'] == CostType.DIRECT)
        indirect = sum(c['amount'] for c in costs if c['type'] == CostType.INDIRECT)
        fixed = sum(c['amount'] for c in costs if c['cost_behavior'] == 'fixed')
        variable = sum(c['amount'] for c in costs if c['cost_behavior'] == 'variable')
        
        cost_items = []
        for c in costs:
            item = CostItem(
                cost_id=c['id'],
                name=c['name'],
                name_hebrew=c['name_hebrew'],
                cost_type=c['type'],
                amount=c['amount'],
                percentage_of_total=(c['amount'] / total * 100) if total else 0,
                unit_cost=c.get('unit_cost'),
                trend=c.get('trend', 'stable'),
                budget=c.get('budget'),
                variance=((c['amount'] - c.get('budget', c['amount'])) / c.get('budget', c['amount']) * 100) if c.get('budget') else None
            )
            cost_items.append(item)
        
        # מגמות
        trends = self._get_cost_trends(6)
        
        # עלות ליחידה
        units_produced = self._get_units_produced(start_date, end_date)
        cost_per_unit = total / units_produced if units_produced else 0
        
        return CostBreakdown(
            period=f"{start_date.isoformat()} - {end_date.isoformat()}",
            total_costs=total,
            direct_costs=direct,
            indirect_costs=indirect,
            fixed_costs=fixed,
            variable_costs=variable,
            cost_items=cost_items,
            cost_per_unit=cost_per_unit,
            cost_trends=trends
        )
    
    def analyze_profitability(
        self,
        dimension: ProfitabilityDimension = ProfitabilityDimension.PRODUCT,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> ProfitabilityAnalysis:
        """
        ניתוח רווחיות
        Profitability Analysis
        """
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = date(end_date.year, 1, 1)
        
        # שליפת נתונים לפי מימד
        items_data = self._get_profitability_data(dimension, start_date, end_date)
        
        items = []
        total_revenue = 0
        total_costs = 0
        
        for i, data in enumerate(items_data):
            gross_profit = data['revenue'] - data['direct_costs']
            gross_margin = (gross_profit / data['revenue'] * 100) if data['revenue'] else 0
            
            allocated_overhead = data['revenue'] * self.overhead_allocation_rate
            net_profit = gross_profit - allocated_overhead
            net_margin = (net_profit / data['revenue'] * 100) if data['revenue'] else 0
            
            roi = (net_profit / data['direct_costs'] * 100) if data['direct_costs'] else 0
            
            recommendations = []
            if net_margin < 5:
                recommendations.append("⚠️ מרווח נמוך - לבחון אפשרות להעלאת מחיר")
            if gross_margin < 30:
                recommendations.append("💡 לבחון הפחתת עלויות ישירות")
            if roi < 15:
                recommendations.append("📊 ROI נמוך - לשקול השקעה חלופית")
            
            item = ProfitabilityItem(
                item_id=data['id'],
                name=data['name'],
                dimension=dimension,
                revenue=data['revenue'],
                direct_costs=data['direct_costs'],
                gross_profit=gross_profit,
                gross_margin=gross_margin,
                allocated_overhead=allocated_overhead,
                net_profit=net_profit,
                net_margin=net_margin,
                roi=roi,
                rank=0,  # יעודכן אחר כך
                recommendations=recommendations
            )
            items.append(item)
            
            total_revenue += data['revenue']
            total_costs += data['direct_costs'] + allocated_overhead
        
        # דירוג לפי רווחיות נטו
        items.sort(key=lambda x: x.net_profit, reverse=True)
        for i, item in enumerate(items):
            item.rank = i + 1
        
        total_profit = total_revenue - total_costs
        average_margin = (total_profit / total_revenue * 100) if total_revenue else 0
        
        # מובילים וחלשים
        top_performers = [item.name for item in items[:3]]
        underperformers = [item.name for item in items if item.net_margin < 5]
        
        # תובנות
        insights = []
        if underperformers:
            insights.append(f"❌ {len(underperformers)} פריטים עם רווחיות נמוכה")
        
        high_margin_items = [item for item in items if item.gross_margin > 50]
        if high_margin_items:
            insights.append(f"✅ {len(high_margin_items)} פריטים עם מרווח גולמי גבוה (>50%)")
        
        top_revenue = items[0] if items else None
        if top_revenue:
            insights.append(f"🏆 {top_revenue.name} מוביל עם ₪{top_revenue.revenue:,.0f} הכנסות")
        
        return ProfitabilityAnalysis(
            analysis_date=date.today().isoformat(),
            dimension=dimension,
            total_revenue=total_revenue,
            total_costs=total_costs,
            total_profit=total_profit,
            average_margin=average_margin,
            items=items,
            top_performers=top_performers,
            underperformers=underperformers,
            insights=insights
        )
    
    def calculate_product_cost(
        self,
        product_id: str
    ) -> ProductCost:
        """
        חישוב עלות מוצר
        Product Cost Calculation
        """
        # נתוני מוצר (בפרודקשן - מDB)
        product = self._get_product_data(product_id)
        
        total_cost = product['material_cost'] + product['labor_cost'] + product['overhead_cost']
        gross_profit = product['selling_price'] - total_cost
        gross_margin = (gross_profit / product['selling_price'] * 100) if product['selling_price'] else 0
        
        # מרווח תרומה (contribution margin)
        variable_costs = product['material_cost'] + product['labor_cost'] * 0.6  # הנחה: 60% עבודה משתנה
        contribution_margin = product['selling_price'] - variable_costs
        
        # נקודת איזון
        fixed_costs_monthly = product['overhead_cost'] * 1000  # הנחה
        break_even = int(fixed_costs_monthly / contribution_margin) if contribution_margin > 0 else 0
        
        return ProductCost(
            product_id=product_id,
            product_name=product['name'],
            selling_price=product['selling_price'],
            material_cost=product['material_cost'],
            labor_cost=product['labor_cost'],
            overhead_cost=product['overhead_cost'],
            total_cost=total_cost,
            gross_profit=gross_profit,
            gross_margin=gross_margin,
            contribution_margin=contribution_margin,
            break_even_units=break_even,
            current_volume=product['volume'],
            is_profitable=gross_profit > 0
        )
    
    def analyze_cogs(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> COGSAnalysis:
        """
        ניתוח עלות המכר
        COGS Analysis
        """
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = date(end_date.year, end_date.month, 1)
        
        # נתוני COGS
        cogs_data = self._get_cogs_data(start_date, end_date)
        revenue = self._get_revenue(start_date, end_date)
        
        total_cogs = sum(c['amount'] for c in cogs_data['components'])
        cogs_pct = (total_cogs / revenue * 100) if revenue else 0
        
        # מגמות
        trends = self._get_cogs_trends(6)
        
        # הזדמנויות לאופטימיזציה
        opportunities = []
        
        if cogs_pct > 65:
            opportunities.append("💰 עלות המכר גבוהה (>65%) - לבחון ספקים חלופיים")
        
        # בדיקת רכיבים
        for comp in cogs_data['components']:
            if comp['percentage'] > 40:
                opportunities.append(f"📦 {comp['name']} מהווה {comp['percentage']:.0f}% מעלות המכר - פוטנציאל לחיסכון")
        
        if cogs_data.get('waste_percentage', 0) > 5:
            opportunities.append("♻️ פחת גבוה - לבחון שיפור בתהליכי ייצור")
        
        return COGSAnalysis(
            period=f"{start_date.isoformat()} - {end_date.isoformat()}",
            total_cogs=total_cogs,
            cogs_percentage=cogs_pct,
            components=cogs_data['components'],
            trends=trends,
            by_category=cogs_data['by_category'],
            optimization_opportunities=opportunities
        )
    
    def get_break_even_analysis(
        self,
        product_id: Optional[str] = None
    ) -> Dict:
        """
        ניתוח נקודת איזון
        Break-Even Analysis
        """
        if product_id:
            products = [self._get_product_data(product_id)]
        else:
            products = self._get_all_products()
        
        results = []
        
        for product in products:
            selling_price = product['selling_price']
            variable_cost = product['material_cost'] + product['labor_cost'] * 0.6
            contribution_margin = selling_price - variable_cost
            contribution_ratio = contribution_margin / selling_price if selling_price else 0
            
            fixed_costs = product['overhead_cost'] * 1000  # חודשי
            
            # נקודת איזון ביחידות
            break_even_units = int(fixed_costs / contribution_margin) if contribution_margin > 0 else 0
            
            # נקודת איזון בכסף
            break_even_revenue = fixed_costs / contribution_ratio if contribution_ratio > 0 else 0
            
            # Margin of Safety
            current_revenue = product['volume'] * selling_price
            margin_of_safety = ((current_revenue - break_even_revenue) / current_revenue * 100) if current_revenue else 0
            
            results.append({
                'product_id': product['id'],
                'product_name': product['name'],
                'selling_price': selling_price,
                'variable_cost': variable_cost,
                'contribution_margin': contribution_margin,
                'contribution_ratio': contribution_ratio * 100,
                'fixed_costs': fixed_costs,
                'break_even_units': break_even_units,
                'break_even_revenue': break_even_revenue,
                'current_volume': product['volume'],
                'current_revenue': current_revenue,
                'margin_of_safety': margin_of_safety,
                'is_above_break_even': product['volume'] > break_even_units
            })
        
        return {
            'analysis_date': date.today().isoformat(),
            'products': results,
            'total_break_even_revenue': sum(r['break_even_revenue'] for r in results),
            'average_margin_of_safety': sum(r['margin_of_safety'] for r in results) / len(results) if results else 0
        }
    
    def get_cost_reduction_opportunities(self) -> List[Dict]:
        """
        הזדמנויות להפחתת עלויות
        Cost Reduction Opportunities
        """
        opportunities = []
        
        # ניתוח עלויות
        cost_breakdown = self.get_cost_breakdown()
        
        # זיהוי עלויות גבוהות
        for cost in cost_breakdown.cost_items:
            if cost.percentage_of_total > 20:
                opportunities.append({
                    'category': cost.name_hebrew,
                    'current_cost': cost.amount,
                    'percentage': cost.percentage_of_total,
                    'potential_savings': cost.amount * 0.1,  # הנחה: 10% חיסכון אפשרי
                    'priority': 'high',
                    'suggestion': f"לבחון מחדש הוצאות {cost.name_hebrew} - מהוות {cost.percentage_of_total:.1f}% מהעלויות"
                })
            
            if cost.variance and cost.variance > 10:
                opportunities.append({
                    'category': cost.name_hebrew,
                    'current_cost': cost.amount,
                    'variance': cost.variance,
                    'budget': cost.budget,
                    'priority': 'medium',
                    'suggestion': f"חריגה מתקציב ב{cost.name_hebrew}: {cost.variance:.1f}% מעל התקציב"
                })
        
        # בדיקת יעילות
        if cost_breakdown.variable_costs > cost_breakdown.fixed_costs * 2:
            opportunities.append({
                'category': 'מבנה עלויות',
                'current_cost': cost_breakdown.variable_costs,
                'priority': 'medium',
                'suggestion': 'עלויות משתנות גבוהות - לבחון אוטומציה או קנה מידה'
            })
        
        # מיון לפי פוטנציאל חיסכון
        opportunities.sort(key=lambda x: x.get('potential_savings', 0), reverse=True)
        
        return opportunities
    
    def _get_costs(self, start_date: date, end_date: date) -> List[Dict]:
        """שליפת עלויות"""
        import random
        return [
            {'id': 'C001', 'name': 'Raw Materials', 'name_hebrew': 'חומרי גלם', 'type': CostType.DIRECT, 'cost_behavior': 'variable', 'amount': random.randint(100000, 150000), 'budget': 120000},
            {'id': 'C002', 'name': 'Direct Labor', 'name_hebrew': 'עבודה ישירה', 'type': CostType.DIRECT, 'cost_behavior': 'variable', 'amount': random.randint(80000, 120000), 'budget': 100000},
            {'id': 'C003', 'name': 'Rent', 'name_hebrew': 'שכירות', 'type': CostType.INDIRECT, 'cost_behavior': 'fixed', 'amount': 25000, 'budget': 25000},
            {'id': 'C004', 'name': 'Utilities', 'name_hebrew': 'חשמל ומים', 'type': CostType.INDIRECT, 'cost_behavior': 'variable', 'amount': random.randint(5000, 8000), 'budget': 6000},
            {'id': 'C005', 'name': 'Salaries', 'name_hebrew': 'משכורות הנהלה', 'type': CostType.INDIRECT, 'cost_behavior': 'fixed', 'amount': 60000, 'budget': 60000},
            {'id': 'C006', 'name': 'Marketing', 'name_hebrew': 'שיווק', 'type': CostType.INDIRECT, 'cost_behavior': 'variable', 'amount': random.randint(15000, 25000), 'budget': 20000},
            {'id': 'C007', 'name': 'Depreciation', 'name_hebrew': 'פחת', 'type': CostType.INDIRECT, 'cost_behavior': 'fixed', 'amount': 8000, 'budget': 8000},
        ]
    
    def _get_cost_trends(self, months: int) -> List[Dict]:
        """מגמות עלויות"""
        import random
        trends = []
        base = 300000
        
        for i in range(months):
            month = (date.today() - timedelta(days=30 * (months - i - 1))).strftime('%Y-%m')
            trends.append({
                'month': month,
                'total_costs': base + random.randint(-20000, 20000),
                'direct': base * 0.6 + random.randint(-10000, 10000),
                'indirect': base * 0.4 + random.randint(-5000, 5000)
            })
        
        return trends
    
    def _get_units_produced(self, start_date: date, end_date: date) -> int:
        """יחידות שיוצרו"""
        import random
        return random.randint(5000, 10000)
    
    def _get_profitability_data(
        self,
        dimension: ProfitabilityDimension,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """נתוני רווחיות"""
        import random
        
        if dimension == ProfitabilityDimension.PRODUCT:
            items = ['מוצר A', 'מוצר B', 'מוצר C', 'מוצר D', 'מוצר E']
        elif dimension == ProfitabilityDimension.CUSTOMER:
            items = ['לקוח ראשי', 'לקוח משני', 'לקוח קמעונאי', 'לקוח B2B', 'לקוח חדש']
        elif dimension == ProfitabilityDimension.SERVICE:
            items = ['שירות ייעוץ', 'שירות תמיכה', 'שירות הטמעה', 'שירות תחזוקה']
        else:
            items = ['יחידה 1', 'יחידה 2', 'יחידה 3']
        
        return [
            {
                'id': f'ITEM-{i}',
                'name': name,
                'revenue': random.randint(50000, 200000),
                'direct_costs': random.randint(30000, 120000)
            }
            for i, name in enumerate(items)
        ]
    
    def _get_product_data(self, product_id: str) -> Dict:
        """נתוני מוצר"""
        import random
        return {
            'id': product_id,
            'name': f'מוצר {product_id}',
            'selling_price': random.randint(100, 500),
            'material_cost': random.randint(30, 150),
            'labor_cost': random.randint(20, 80),
            'overhead_cost': random.randint(10, 40),
            'volume': random.randint(500, 2000)
        }
    
    def _get_all_products(self) -> List[Dict]:
        """כל המוצרים"""
        return [self._get_product_data(f'P{i}') for i in range(1, 6)]
    
    def _get_cogs_data(self, start_date: date, end_date: date) -> Dict:
        """נתוני עלות המכר"""
        import random
        return {
            'components': [
                {'name': 'חומרי גלם', 'amount': random.randint(100000, 150000), 'percentage': 45},
                {'name': 'עבודה ישירה', 'amount': random.randint(60000, 90000), 'percentage': 30},
                {'name': 'תקורה ייצור', 'amount': random.randint(30000, 50000), 'percentage': 20},
                {'name': 'אריזה והובלה', 'amount': random.randint(10000, 20000), 'percentage': 5}
            ],
            'by_category': {
                'מוצר A': random.randint(50000, 80000),
                'מוצר B': random.randint(40000, 70000),
                'מוצר C': random.randint(30000, 50000)
            },
            'waste_percentage': random.uniform(2, 8)
        }
    
    def _get_cogs_trends(self, months: int) -> List[Dict]:
        """מגמות עלות המכר"""
        import random
        trends = []
        
        for i in range(months):
            month = (date.today() - timedelta(days=30 * (months - i - 1))).strftime('%Y-%m')
            trends.append({
                'month': month,
                'cogs': random.randint(200000, 280000),
                'cogs_percentage': random.uniform(55, 65)
            })
        
        return trends
    
    def _get_revenue(self, start_date: date, end_date: date) -> float:
        """הכנסות"""
        import random
        return random.randint(400000, 600000)
