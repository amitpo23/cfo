"""
AI-powered financial insights
תובנות פיננסיות מבוססות בינה מלאכותית
"""
from typing import Optional, Dict, Any
from datetime import datetime
from openai import OpenAI

from ..config import settings
from .financial_service import FinancialService


class AIInsightsService:
    """שירות לתובנות פיננסיות באמצעות AI"""
    
    def __init__(self, financial_service: FinancialService):
        self.financial_service = financial_service
        self.client = None
        
        if settings.openai_api_key:
            self.client = OpenAI(api_key=settings.openai_api_key)
    
    def _check_client(self):
        """בדיקה שה-API key של OpenAI קיים"""
        if not self.client:
            raise ValueError(
                "OpenAI API key not configured. "
                "Please set OPENAI_API_KEY in your .env file"
            )
    
    async def analyze_financial_status(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> str:
        """ניתוח מצב פיננסי עם המלצות"""
        self._check_client()
        
        # שליפת נתונים פיננסיים
        summary = self.financial_service.get_financial_summary(
            start_date=start_date,
            end_date=end_date
        )
        
        # הכנת הנתונים לשליחה ל-AI
        financial_data = f"""
        נתונים פיננסיים:
        - תקופה: {summary.period_start.strftime('%Y-%m-%d')} עד {summary.period_end.strftime('%Y-%m-%d')}
        - סך נכסים: ₪{summary.total_assets:,.2f}
        - סך התחייבויות: ₪{summary.total_liabilities:,.2f}
        - הון עצמי: ₪{summary.net_worth:,.2f}
        - סך הכנסות בתקופה: ₪{summary.total_income:,.2f}
        - סך הוצאות בתקופה: ₪{summary.total_expenses:,.2f}
        - רווח/הפסד נקי: ₪{summary.net_income:,.2f}
        """
        
        # קריאה ל-OpenAI
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "אתה יועץ פיננסי מומחה המספק ניתוח והמלצות בעברית. "
                        "נתח את המצב הפיננסי והצע המלצות מעשיות."
                    )
                },
                {
                    "role": "user",
                    "content": f"נתח את המצב הפיננסי הבא וספק המלצות:\n\n{financial_data}"
                }
            ],
            temperature=0.7,
            max_tokens=1000
        )
        
        return response.choices[0].message.content
    
    async def explain_transaction_pattern(
        self,
        category: Optional[str] = None
    ) -> str:
        """הסבר על דפוסי עסקאות"""
        self._check_client()
        
        # שליפת עסקאות אחרונות
        transactions = self.financial_service.get_transactions(limit=50)
        
        # הכנת סיכום עסקאות
        trans_summary = "\n".join([
            f"- {t.transaction_date.strftime('%Y-%m-%d')}: {t.transaction_type.value}, "
            f"₪{t.amount:.2f}, {t.description or 'ללא תיאור'}"
            for t in transactions[:20]
        ])
        
        prompt = f"""
        להלן 20 העסקאות האחרונות:
        {trans_summary}
        
        נתח את הדפוסים בעסקאות אלו והסבר מה ניתן ללמוד מהן.
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "אתה מנתח פיננסי המתמחה בזיהוי דפוסים והתנהגויות בעסקאות פיננסיות."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        return response.choices[0].message.content
    
    async def get_recommendation(self, question: str) -> str:
        """קבלת המלצה או תשובה לשאלה פיננסית"""
        self._check_client()
        
        # שליפת סיכום פיננסי עדכני
        summary = self.financial_service.get_financial_summary()
        
        context = f"""
        מצב פיננסי נוכחי:
        - הון עצמי: ₪{summary.net_worth:,.2f}
        - הכנסות חודשיות (ממוצע): ₪{summary.total_income:,.2f}
        - הוצאות חודשיות (ממוצע): ₪{summary.total_expenses:,.2f}
        """
        
        response = self.client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "אתה CFO וירטואלי המייעץ בנושאים פיננסיים. "
                        "ענה בצורה ברורה ומעשית בעברית."
                    )
                },
                {
                    "role": "user",
                    "content": f"{context}\n\nשאלה: {question}"
                }
            ],
            temperature=0.7,
            max_tokens=600
        )
        
        return response.choices[0].message.content
