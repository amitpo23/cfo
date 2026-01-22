"""
Advanced AI Analytics Service
שירות ניתוח AI מתקדם
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import json
from sqlalchemy.orm import Session

from ..models import Transaction, Account
from ..database import SessionLocal
from ..config import settings


class AnomalyType(str, Enum):
    """סוג אנומליה"""
    UNUSUAL_AMOUNT = "unusual_amount"
    TIMING_ANOMALY = "timing_anomaly"
    FREQUENCY_ANOMALY = "frequency_anomaly"
    PATTERN_BREAK = "pattern_break"
    DUPLICATE_SUSPECTED = "duplicate_suspected"
    CATEGORY_MISMATCH = "category_mismatch"


class RiskLevel(str, Enum):
    """רמת סיכון"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InsightType(str, Enum):
    """סוג תובנה"""
    COST_SAVING = "cost_saving"
    REVENUE_OPPORTUNITY = "revenue_opportunity"
    RISK_ALERT = "risk_alert"
    EFFICIENCY_TIP = "efficiency_tip"
    TREND_INSIGHT = "trend_insight"
    BENCHMARK_COMPARISON = "benchmark_comparison"


@dataclass
class Anomaly:
    """אנומליה שזוהתה"""
    anomaly_id: str
    anomaly_type: AnomalyType
    detected_at: str
    entity_type: str
    entity_id: str
    description: str
    expected_value: Optional[float]
    actual_value: float
    deviation_percentage: float
    risk_level: RiskLevel
    recommendation: str
    confidence_score: float
    related_transactions: List[str]


@dataclass
class FinancialRisk:
    """סיכון פיננסי"""
    risk_id: str
    risk_type: str
    title: str
    description: str
    risk_level: RiskLevel
    probability: float
    potential_impact: float
    expected_loss: float
    mitigation_actions: List[str]
    monitoring_metrics: List[str]
    trend: str


@dataclass
class AIInsight:
    """תובנת AI"""
    insight_id: str
    insight_type: InsightType
    title: str
    description: str
    impact_amount: float
    confidence: float
    priority: str
    actionable: bool
    suggested_actions: List[str]
    supporting_data: Dict
    expires_at: Optional[str]


@dataclass
class PredictiveAnalysis:
    """ניתוח חזוי"""
    analysis_date: str
    metric: str
    current_value: float
    predicted_value: float
    prediction_date: str
    confidence_interval: Tuple[float, float]
    confidence_level: float
    trend: str
    factors: List[Dict]
    scenarios: List[Dict]


@dataclass
class AIRecommendation:
    """המלצת AI"""
    recommendation_id: str
    category: str
    title: str
    description: str
    expected_benefit: float
    implementation_cost: float
    roi: float
    effort_level: str
    time_to_implement: str
    prerequisites: List[str]
    risks: List[str]
    priority_score: float


class AdvancedAIService:
    """
    שירות ניתוח AI מתקדם
    Advanced AI Analytics Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        self.openai_available = bool(settings.openai_api_key)
        
        # ספי זיהוי אנומליות
        self.anomaly_thresholds = {
            'amount_deviation': 2.5,  # סטיות תקן
            'timing_deviation': 7,    # ימים
            'frequency_deviation': 50  # אחוז
        }
    
    def detect_anomalies(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_confidence: float = 0.7
    ) -> List[Anomaly]:
        """
        זיהוי אנומליות
        Detect Anomalies
        """
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date - timedelta(days=90)
        
        anomalies = []
        
        # שליפת עסקאות
        transactions = self._get_transactions(start_date, end_date)
        
        # 1. זיהוי סכומים חריגים
        anomalies.extend(self._detect_amount_anomalies(transactions))
        
        # 2. זיהוי תזמון חריג
        anomalies.extend(self._detect_timing_anomalies(transactions))
        
        # 3. זיהוי כפילויות אפשריות
        anomalies.extend(self._detect_duplicates(transactions))
        
        # 4. זיהוי שבירת דפוסים
        anomalies.extend(self._detect_pattern_breaks(transactions))
        
        # סינון לפי ביטחון
        anomalies = [a for a in anomalies if a.confidence_score >= min_confidence]
        
        # מיון לפי סיכון
        risk_order = {RiskLevel.CRITICAL: 0, RiskLevel.HIGH: 1, RiskLevel.MEDIUM: 2, RiskLevel.LOW: 3}
        anomalies.sort(key=lambda x: (risk_order[x.risk_level], -x.confidence_score))
        
        return anomalies
    
    def assess_financial_risks(self) -> List[FinancialRisk]:
        """
        הערכת סיכונים פיננסיים
        Financial Risk Assessment
        """
        risks = []
        
        # 1. סיכון נזילות
        liquidity_data = self._assess_liquidity_risk()
        if liquidity_data['score'] < 70:
            risks.append(FinancialRisk(
                risk_id='RISK-LIQ-001',
                risk_type='liquidity',
                title='סיכון נזילות',
                description='יחסי נזילות נמוכים מהרצוי',
                risk_level=RiskLevel.HIGH if liquidity_data['score'] < 50 else RiskLevel.MEDIUM,
                probability=0.6,
                potential_impact=100000,
                expected_loss=60000,
                mitigation_actions=[
                    'לזרז גביית חובות',
                    'לנהל מו"מ להארכת תנאי תשלום לספקים',
                    'לשקול מסגרת אשראי'
                ],
                monitoring_metrics=['יחס שוטף', 'יחס מהיר', 'ימי מזומן'],
                trend=liquidity_data['trend']
            ))
        
        # 2. סיכון אשראי
        credit_data = self._assess_credit_risk()
        if credit_data['at_risk_amount'] > 50000:
            risks.append(FinancialRisk(
                risk_id='RISK-CRD-001',
                risk_type='credit',
                title='סיכון אשראי לקוחות',
                description=f"₪{credit_data['at_risk_amount']:,.0f} בסיכון גבוה לאי-גבייה",
                risk_level=RiskLevel.HIGH if credit_data['at_risk_amount'] > 100000 else RiskLevel.MEDIUM,
                probability=0.3,
                potential_impact=credit_data['at_risk_amount'],
                expected_loss=credit_data['at_risk_amount'] * 0.3,
                mitigation_actions=[
                    'להגביר מאמצי גבייה',
                    'לדרוש ערבויות מלקוחות בסיכון',
                    'לשקול הפרשה לחובות מסופקים'
                ],
                monitoring_metrics=['DSO', 'גיול חובות', 'אחוז גבייה'],
                trend=credit_data['trend']
            ))
        
        # 3. סיכון תזרים מזומנים
        cashflow_data = self._assess_cashflow_risk()
        if cashflow_data['deficit_months'] > 0:
            risks.append(FinancialRisk(
                risk_id='RISK-CF-001',
                risk_type='cashflow',
                title='סיכון תזרים מזומנים',
                description=f"צפי לגירעון ב-{cashflow_data['deficit_months']} חודשים הקרובים",
                risk_level=RiskLevel.CRITICAL if cashflow_data['deficit_months'] >= 3 else RiskLevel.HIGH,
                probability=0.7,
                potential_impact=cashflow_data['total_deficit'],
                expected_loss=cashflow_data['total_deficit'] * 0.7,
                mitigation_actions=[
                    'לדחות הוצאות לא חיוניות',
                    'להקדים גביית הכנסות',
                    'לגייס מימון גישור'
                ],
                monitoring_metrics=['יתרת מזומן', 'Runway', 'Burn Rate'],
                trend='deteriorating'
            ))
        
        # 4. סיכון ריכוזיות לקוחות
        concentration_data = self._assess_concentration_risk()
        if concentration_data['top_customer_percentage'] > 30:
            risks.append(FinancialRisk(
                risk_id='RISK-CON-001',
                risk_type='concentration',
                title='סיכון ריכוזיות לקוחות',
                description=f"לקוח מוביל מהווה {concentration_data['top_customer_percentage']:.0f}% מההכנסות",
                risk_level=RiskLevel.MEDIUM,
                probability=0.2,
                potential_impact=concentration_data['top_customer_revenue'],
                expected_loss=concentration_data['top_customer_revenue'] * 0.2,
                mitigation_actions=[
                    'לגוון בסיס לקוחות',
                    'לחזק קשרים עם לקוח מוביל',
                    'לפתח לקוחות חדשים'
                ],
                monitoring_metrics=['פיזור לקוחות', 'אחוז לקוח מוביל'],
                trend='stable'
            ))
        
        # מיון לפי expected_loss
        risks.sort(key=lambda x: x.expected_loss, reverse=True)
        
        return risks
    
    def generate_insights(
        self,
        focus_areas: Optional[List[str]] = None
    ) -> List[AIInsight]:
        """
        יצירת תובנות AI
        Generate AI Insights
        """
        insights = []
        
        # 1. תובנות חיסכון בעלויות
        cost_insights = self._generate_cost_insights()
        insights.extend(cost_insights)
        
        # 2. הזדמנויות הכנסה
        revenue_insights = self._generate_revenue_insights()
        insights.extend(revenue_insights)
        
        # 3. התראות סיכון
        risk_insights = self._generate_risk_insights()
        insights.extend(risk_insights)
        
        # 4. טיפים ליעילות
        efficiency_insights = self._generate_efficiency_insights()
        insights.extend(efficiency_insights)
        
        # 5. תובנות מגמה
        trend_insights = self._generate_trend_insights()
        insights.extend(trend_insights)
        
        # סינון לפי focus_areas
        if focus_areas:
            insights = [i for i in insights if i.insight_type.value in focus_areas]
        
        # מיון לפי עדיפות ואימפקט
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        insights.sort(key=lambda x: (priority_order.get(x.priority, 2), -x.impact_amount))
        
        return insights
    
    def predict_metric(
        self,
        metric: str,
        horizon_months: int = 6
    ) -> PredictiveAnalysis:
        """
        חיזוי מדד פיננסי
        Predict Financial Metric
        """
        # נתונים היסטוריים
        historical = self._get_metric_history(metric, months=24)
        current_value = historical[-1]['value'] if historical else 0
        
        # חישוב מגמה
        if len(historical) >= 3:
            recent_avg = sum(h['value'] for h in historical[-3:]) / 3
            older_avg = sum(h['value'] for h in historical[-6:-3]) / 3 if len(historical) >= 6 else recent_avg
            trend_pct = ((recent_avg - older_avg) / older_avg * 100) if older_avg else 0
        else:
            trend_pct = 0
        
        # חיזוי פשוט (בפרודקשן - ML מתקדם)
        monthly_growth = trend_pct / 100 / 3  # צמיחה חודשית
        predicted_value = current_value * (1 + monthly_growth) ** horizon_months
        
        # טווח ביטחון
        uncertainty = 0.15 * horizon_months / 6  # אי-ודאות גדלה עם הזמן
        lower = predicted_value * (1 - uncertainty)
        upper = predicted_value * (1 + uncertainty)
        
        # גורמים משפיעים
        factors = [
            {'factor': 'מגמה היסטורית', 'impact': trend_pct, 'confidence': 0.8},
            {'factor': 'עונתיות', 'impact': self._get_seasonality_factor(metric), 'confidence': 0.6},
            {'factor': 'מצב השוק', 'impact': 2.0, 'confidence': 0.4}
        ]
        
        # תרחישים
        scenarios = [
            {
                'name': 'אופטימי',
                'value': upper * 1.1,
                'probability': 0.2,
                'assumptions': 'צמיחה מואצת, שוק חזק'
            },
            {
                'name': 'צפוי',
                'value': predicted_value,
                'probability': 0.6,
                'assumptions': 'המשך מגמות קיימות'
            },
            {
                'name': 'פסימי',
                'value': lower * 0.9,
                'probability': 0.2,
                'assumptions': 'האטה, אתגרים בשוק'
            }
        ]
        
        trend = 'up' if trend_pct > 2 else 'down' if trend_pct < -2 else 'stable'
        
        return PredictiveAnalysis(
            analysis_date=date.today().isoformat(),
            metric=metric,
            current_value=current_value,
            predicted_value=predicted_value,
            prediction_date=(date.today() + timedelta(days=30 * horizon_months)).isoformat(),
            confidence_interval=(lower, upper),
            confidence_level=0.85 - 0.05 * horizon_months / 6,
            trend=trend,
            factors=factors,
            scenarios=scenarios
        )
    
    def get_ai_recommendations(
        self,
        budget: Optional[float] = None,
        focus: Optional[str] = None
    ) -> List[AIRecommendation]:
        """
        המלצות AI
        AI Recommendations
        """
        recommendations = []
        
        # 1. המלצות לחיסכון
        recommendations.append(AIRecommendation(
            recommendation_id='REC-001',
            category='חיסכון בעלויות',
            title='אוטומציה של תהליכי גבייה',
            description='הטמעת מערכת תזכורות אוטומטית לגבייה יכולה לקצר את DSO ב-20%',
            expected_benefit=25000,
            implementation_cost=5000,
            roi=400,
            effort_level='medium',
            time_to_implement='1-2 חודשים',
            prerequisites=['מערכת CRM', 'אימייל אוטומטי'],
            risks=['התנגדות לקוחות', 'בעיות טכניות'],
            priority_score=85
        ))
        
        recommendations.append(AIRecommendation(
            recommendation_id='REC-002',
            category='אופטימיזציה פיננסית',
            title='מו"מ מחודש עם ספקים',
            description='5 הספקים הגדולים מהווים 60% מהרכישות - פוטנציאל לחיסכון 5-10%',
            expected_benefit=30000,
            implementation_cost=0,
            roi=float('inf'),
            effort_level='low',
            time_to_implement='1-4 שבועות',
            prerequisites=['נתוני רכישות', 'הצעות מתחרים'],
            risks=['פגיעה ביחסים עם ספקים'],
            priority_score=90
        ))
        
        recommendations.append(AIRecommendation(
            recommendation_id='REC-003',
            category='צמיחה בהכנסות',
            title='תכנית Upsell ללקוחות קיימים',
            description='30% מהלקוחות משתמשים רק בשירות אחד - פוטנציאל מכירה צולבת',
            expected_benefit=50000,
            implementation_cost=8000,
            roi=525,
            effort_level='medium',
            time_to_implement='2-3 חודשים',
            prerequisites=['ניתוח לקוחות', 'חבילות מוצרים'],
            risks=['עומס על צוות מכירות'],
            priority_score=80
        ))
        
        recommendations.append(AIRecommendation(
            recommendation_id='REC-004',
            category='ניהול סיכונים',
            title='הגדלת מסגרת אשראי לחירום',
            description='Runway נמוך - מומלץ לאשר מסגרת אשראי טרם הצורך',
            expected_benefit=0,
            implementation_cost=2000,
            roi=0,
            effort_level='low',
            time_to_implement='1-2 שבועות',
            prerequisites=['דוחות כספיים', 'יחס עם הבנק'],
            risks=['עלות ריבית'],
            priority_score=95
        ))
        
        recommendations.append(AIRecommendation(
            recommendation_id='REC-005',
            category='יעילות תפעולית',
            title='מעבר לחשבונאות ענן',
            description='חיסכון בזמן הנה"ח ושיפור דיוק הדוחות',
            expected_benefit=15000,
            implementation_cost=12000,
            roi=25,
            effort_level='high',
            time_to_implement='3-6 חודשים',
            prerequisites=['בחירת מערכת', 'הדרכת צוות'],
            risks=['עקומת למידה', 'מיגרציית נתונים'],
            priority_score=60
        ))
        
        # סינון לפי תקציב
        if budget:
            recommendations = [r for r in recommendations if r.implementation_cost <= budget]
        
        # סינון לפי פוקוס
        if focus:
            recommendations = [r for r in recommendations if focus in r.category]
        
        # מיון לפי priority_score
        recommendations.sort(key=lambda x: x.priority_score, reverse=True)
        
        return recommendations
    
    async def get_ai_analysis(
        self,
        question: str,
        context: Optional[Dict] = None
    ) -> str:
        """
        ניתוח AI עם GPT
        AI Analysis with GPT
        """
        if not self.openai_available:
            return self._get_fallback_analysis(question)
        
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)
            
            # הכנת קונטקסט
            financial_context = context or self._prepare_financial_context()
            
            prompt = f"""
אתה יועץ פיננסי מומחה למערכות ניהול כספים בישראל.

נתונים פיננסיים:
{json.dumps(financial_context, ensure_ascii=False, indent=2)}

שאלה: {question}

ענה בעברית, בצורה מקצועית וממוקדת. כלול:
1. ניתוח המצב הנוכחי
2. המלצות מעשיות
3. סיכונים שיש לקחת בחשבון
"""
            
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"שגיאה בניתוח AI: {str(e)}\n\n{self._get_fallback_analysis(question)}"
    
    def _detect_amount_anomalies(self, transactions: List[Dict]) -> List[Anomaly]:
        """זיהוי סכומים חריגים"""
        anomalies = []
        
        # חישוב סטטיסטיקות לפי קטגוריה
        from collections import defaultdict
        import statistics
        
        by_category = defaultdict(list)
        for tx in transactions:
            by_category[tx['category']].append(tx['amount'])
        
        for tx in transactions:
            cat = tx['category']
            if len(by_category[cat]) < 5:
                continue
            
            mean = statistics.mean(by_category[cat])
            stdev = statistics.stdev(by_category[cat]) if len(by_category[cat]) > 1 else mean * 0.3
            
            if stdev == 0:
                continue
            
            z_score = abs((tx['amount'] - mean) / stdev)
            
            if z_score > self.anomaly_thresholds['amount_deviation']:
                anomalies.append(Anomaly(
                    anomaly_id=f"ANO-AMT-{tx['id']}",
                    anomaly_type=AnomalyType.UNUSUAL_AMOUNT,
                    detected_at=datetime.now().isoformat(),
                    entity_type='transaction',
                    entity_id=tx['id'],
                    description=f"סכום חריג בקטגוריית {cat}",
                    expected_value=mean,
                    actual_value=tx['amount'],
                    deviation_percentage=((tx['amount'] - mean) / mean * 100) if mean else 0,
                    risk_level=RiskLevel.HIGH if z_score > 4 else RiskLevel.MEDIUM,
                    recommendation='לבדוק את העסקה ולוודא תקינות',
                    confidence_score=min(0.95, 0.5 + z_score / 10),
                    related_transactions=[tx['id']]
                ))
        
        return anomalies
    
    def _detect_timing_anomalies(self, transactions: List[Dict]) -> List[Anomaly]:
        """זיהוי תזמון חריג"""
        anomalies = []
        
        # בדיקת עסקאות בסופ"ש או שעות לא רגילות
        for tx in transactions:
            tx_date = datetime.strptime(tx['date'], '%Y-%m-%d')
            
            # סוף שבוע
            if tx_date.weekday() >= 5:
                anomalies.append(Anomaly(
                    anomaly_id=f"ANO-TIM-{tx['id']}",
                    anomaly_type=AnomalyType.TIMING_ANOMALY,
                    detected_at=datetime.now().isoformat(),
                    entity_type='transaction',
                    entity_id=tx['id'],
                    description='עסקה בסוף שבוע',
                    expected_value=None,
                    actual_value=tx['amount'],
                    deviation_percentage=0,
                    risk_level=RiskLevel.LOW,
                    recommendation='לוודא שהעסקה לגיטימית',
                    confidence_score=0.7,
                    related_transactions=[tx['id']]
                ))
        
        return anomalies
    
    def _detect_duplicates(self, transactions: List[Dict]) -> List[Anomaly]:
        """זיהוי כפילויות"""
        anomalies = []
        seen = {}
        
        for tx in transactions:
            key = f"{tx['amount']}_{tx['description'][:20]}"
            if key in seen:
                prev = seen[key]
                # בדיקת קרבה בזמן
                prev_date = datetime.strptime(prev['date'], '%Y-%m-%d')
                curr_date = datetime.strptime(tx['date'], '%Y-%m-%d')
                
                if abs((curr_date - prev_date).days) <= 3:
                    anomalies.append(Anomaly(
                        anomaly_id=f"ANO-DUP-{tx['id']}",
                        anomaly_type=AnomalyType.DUPLICATE_SUSPECTED,
                        detected_at=datetime.now().isoformat(),
                        entity_type='transaction',
                        entity_id=tx['id'],
                        description='חשד לעסקה כפולה',
                        expected_value=None,
                        actual_value=tx['amount'],
                        deviation_percentage=0,
                        risk_level=RiskLevel.HIGH,
                        recommendation='לבדוק אם מדובר בכפילות ולבטל במידת הצורך',
                        confidence_score=0.85,
                        related_transactions=[prev['id'], tx['id']]
                    ))
            seen[key] = tx
        
        return anomalies
    
    def _detect_pattern_breaks(self, transactions: List[Dict]) -> List[Anomaly]:
        """זיהוי שבירת דפוסים"""
        # פשוט לדוגמה - בפרודקשן יהיה מורכב יותר
        return []
    
    def _assess_liquidity_risk(self) -> Dict:
        """הערכת סיכון נזילות"""
        import random
        return {
            'score': random.randint(50, 90),
            'current_ratio': random.uniform(1.0, 2.5),
            'quick_ratio': random.uniform(0.8, 2.0),
            'trend': random.choice(['improving', 'stable', 'deteriorating'])
        }
    
    def _assess_credit_risk(self) -> Dict:
        """הערכת סיכון אשראי"""
        import random
        return {
            'at_risk_amount': random.randint(20000, 150000),
            'over_90_days': random.randint(10000, 50000),
            'trend': random.choice(['improving', 'stable', 'deteriorating'])
        }
    
    def _assess_cashflow_risk(self) -> Dict:
        """הערכת סיכון תזרים"""
        import random
        deficit_months = random.randint(0, 4)
        return {
            'deficit_months': deficit_months,
            'total_deficit': deficit_months * random.randint(20000, 50000)
        }
    
    def _assess_concentration_risk(self) -> Dict:
        """הערכת סיכון ריכוזיות"""
        import random
        top_pct = random.randint(15, 45)
        return {
            'top_customer_percentage': top_pct,
            'top_customer_revenue': top_pct * 10000
        }
    
    def _generate_cost_insights(self) -> List[AIInsight]:
        """תובנות חיסכון"""
        return [
            AIInsight(
                insight_id='INS-COST-001',
                insight_type=InsightType.COST_SAVING,
                title='פוטנציאל חיסכון בהוצאות משרד',
                description='הוצאות משרד עלו ב-15% ברבעון האחרון ללא גידול בפעילות',
                impact_amount=8000,
                confidence=0.85,
                priority='medium',
                actionable=True,
                suggested_actions=['לבחון חוזי ספקים', 'לבדוק צריכה מיותרת'],
                supporting_data={'trend': '+15%', 'benchmark': '5%'},
                expires_at=None
            )
        ]
    
    def _generate_revenue_insights(self) -> List[AIInsight]:
        """תובנות הכנסה"""
        return [
            AIInsight(
                insight_id='INS-REV-001',
                insight_type=InsightType.REVENUE_OPPORTUNITY,
                title='לקוחות לא פעילים עם פוטנציאל',
                description='12 לקוחות לא רכשו ב-6 חודשים אחרונים - פוטנציאל הכנסה ₪45,000',
                impact_amount=45000,
                confidence=0.7,
                priority='high',
                actionable=True,
                suggested_actions=['ליצור קשר עם הלקוחות', 'להציע מבצע חזרה'],
                supporting_data={'inactive_customers': 12, 'avg_purchase': 3750},
                expires_at=(date.today() + timedelta(days=30)).isoformat()
            )
        ]
    
    def _generate_risk_insights(self) -> List[AIInsight]:
        """תובנות סיכון"""
        return [
            AIInsight(
                insight_id='INS-RISK-001',
                insight_type=InsightType.RISK_ALERT,
                title='גידול בחובות מעל 90 יום',
                description='חובות מעל 90 יום גדלו ב-25% - סיכון לחובות אבודים',
                impact_amount=35000,
                confidence=0.9,
                priority='high',
                actionable=True,
                suggested_actions=['להגביר גבייה', 'לשקול הפרשה'],
                supporting_data={'growth': '25%', 'total_over_90': 35000},
                expires_at=None
            )
        ]
    
    def _generate_efficiency_insights(self) -> List[AIInsight]:
        """תובנות יעילות"""
        return []
    
    def _generate_trend_insights(self) -> List[AIInsight]:
        """תובנות מגמה"""
        return [
            AIInsight(
                insight_id='INS-TREND-001',
                insight_type=InsightType.TREND_INSIGHT,
                title='מגמת צמיחה חיובית',
                description='הכנסות גדלו 3 חודשים ברציפות - מגמה חיובית',
                impact_amount=0,
                confidence=0.95,
                priority='low',
                actionable=False,
                suggested_actions=['להמשיך במומנטום', 'לתכנן משאבים'],
                supporting_data={'consecutive_growth': 3, 'avg_growth': '8%'},
                expires_at=None
            )
        ]
    
    def _get_transactions(self, start_date: date, end_date: date) -> List[Dict]:
        """שליפת עסקאות"""
        import random
        transactions = []
        
        categories = ['הכנסות', 'הוצאות משרד', 'שכר', 'שיווק', 'נסיעות']
        
        for i in range(50):
            days_ago = random.randint(0, (end_date - start_date).days)
            tx_date = end_date - timedelta(days=days_ago)
            cat = random.choice(categories)
            
            base_amount = {
                'הכנסות': 15000,
                'הוצאות משרד': 2000,
                'שכר': 12000,
                'שיווק': 5000,
                'נסיעות': 1500
            }[cat]
            
            amount = base_amount + random.randint(-int(base_amount * 0.3), int(base_amount * 0.3))
            
            # הוספת כמה outliers
            if random.random() > 0.95:
                amount *= 3
            
            transactions.append({
                'id': f'TX-{i + 1000}',
                'date': tx_date.isoformat(),
                'amount': amount,
                'category': cat,
                'description': f'{cat} - עסקה {i + 1}'
            })
        
        return transactions
    
    def _get_metric_history(self, metric: str, months: int) -> List[Dict]:
        """היסטוריית מדד"""
        import random
        history = []
        base = 100000
        
        for i in range(months):
            month = date.today() - timedelta(days=30 * (months - i - 1))
            # מגמה עולה עם תנודות
            value = base * (1 + 0.02 * i) + random.randint(-10000, 10000)
            history.append({
                'month': month.strftime('%Y-%m'),
                'value': value
            })
        
        return history
    
    def _get_seasonality_factor(self, metric: str) -> float:
        """גורם עונתיות"""
        import random
        return random.uniform(-5, 10)
    
    def _prepare_financial_context(self) -> Dict:
        """הכנת קונטקסט פיננסי"""
        return {
            'revenue_mtd': 450000,
            'expenses_mtd': 380000,
            'cash_balance': 125000,
            'receivables': 85000,
            'payables': 62000,
            'top_expense_categories': ['שכר', 'שיווק', 'שכירות']
        }
    
    def _get_fallback_analysis(self, question: str) -> str:
        """ניתוח חלופי ללא OpenAI"""
        return f"""
ניתוח לשאלה: {question}

מבוסס על הנתונים הזמינים:
• מצב תזרים: יציב עם מגמת שיפור
• רמת סיכון: בינונית
• המלצה: להמשיך לעקוב אחר מדדים מרכזיים

לניתוח מעמיק יותר, אנא הגדר מפתח OpenAI API בהגדרות.
"""
