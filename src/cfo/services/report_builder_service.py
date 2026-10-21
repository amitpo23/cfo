"""
Report Builder & Scheduler Service
שירות בונה דוחות ותזמון
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
import json
import asyncio
import logging
from pathlib import Path
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..config import settings

logger = logging.getLogger(__name__)


class ReportFormat(str, Enum):
    """פורמט דוח"""
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"
    JSON = "json"
    HTML = "html"


class ReportFrequency(str, Enum):
    """תדירות דוח"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    ON_DEMAND = "on_demand"


class ReportType(str, Enum):
    """סוג דוח"""
    PROFIT_LOSS = "profit_loss"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    AGING_REPORT = "aging_report"
    BUDGET_VS_ACTUAL = "budget_vs_actual"
    KPI_DASHBOARD = "kpi_dashboard"
    VAT_REPORT = "vat_report"
    CUSTOM = "custom"


class DeliveryMethod(str, Enum):
    """שיטת משלוח"""
    EMAIL = "email"
    DOWNLOAD = "download"
    WEBHOOK = "webhook"
    SFTP = "sftp"
    GOOGLE_DRIVE = "google_drive"


@dataclass
class ReportColumn:
    """עמודת דוח"""
    field_name: str
    display_name: str
    data_type: str  # string, number, date, currency, percentage
    width: Optional[int] = None
    format_string: Optional[str] = None
    aggregation: Optional[str] = None  # sum, avg, count, min, max
    sortable: bool = True
    filterable: bool = True


@dataclass
class ReportFilter:
    """פילטר דוח"""
    field_name: str
    operator: str  # eq, ne, gt, gte, lt, lte, in, contains, between
    value: Any
    label: Optional[str] = None


@dataclass
class ReportTemplate:
    """תבנית דוח"""
    template_id: str
    name: str
    description: str
    report_type: ReportType
    columns: List[ReportColumn]
    default_filters: List[ReportFilter]
    grouping: List[str]
    sorting: List[Dict]  # [{'field': 'amount', 'direction': 'desc'}]
    summary_fields: List[str]
    created_by: str
    created_at: str
    is_public: bool
    organization_id: int
    version: int = 1


@dataclass
class ScheduledReport:
    """דוח מתוזמן"""
    schedule_id: str
    template_id: str
    name: str
    frequency: ReportFrequency
    next_run: str
    last_run: Optional[str]
    recipients: List[str]
    delivery_method: DeliveryMethod
    format: ReportFormat
    filters: List[ReportFilter]
    is_active: bool
    created_by: str
    organization_id: int
    parameters: Dict
    version: int = 1


@dataclass
class GeneratedReport:
    """דוח שנוצר"""
    report_id: str
    template_id: str
    generated_at: str
    format: ReportFormat
    file_path: Optional[str]
    file_size: int
    row_count: int
    generation_time_ms: int
    filters_applied: List[Dict]
    generated_by: str
    expires_at: str
    download_url: Optional[str]


@dataclass
class ReportExecution:
    """ביצוע דוח"""
    execution_id: str
    schedule_id: Optional[str]
    template_id: str
    status: str  # pending, running, completed, failed
    started_at: str
    completed_at: Optional[str]
    error_message: Optional[str]
    result: Optional[GeneratedReport]


class ReportBuilderService:
    """
    שירות בניית דוחות ותזמון
    Report Builder & Scheduler Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        self.reports_dir = Path(settings.reports_dir if hasattr(settings, 'reports_dir') else './reports')
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        # תבניות ברירת מחדל
        self._default_templates = self._create_default_templates()
        
        from .report_storage import ReportStore
        self._templates = ReportStore(db, organization_id, 'template', self._decode_template)
        self._schedules = ReportStore(db, organization_id, 'schedule', self._decode_schedule)
        self._executions = ReportStore(db, organization_id, 'execution', self._decode_execution)
        self._files = ReportStore(db, organization_id, 'file', dict)
    
    @staticmethod
    def _decode_template(payload):
        data = dict(payload)
        data['report_type'] = ReportType(data['report_type'])
        data['columns'] = [ReportColumn(**c) for c in data['columns']]
        data['default_filters'] = [ReportFilter(**f) for f in data['default_filters']]
        return ReportTemplate(**data)

    @staticmethod
    def _decode_schedule(payload):
        data = dict(payload)
        data['frequency'] = ReportFrequency(data['frequency'])
        data['format'] = ReportFormat(data['format'])
        data['delivery_method'] = DeliveryMethod(data['delivery_method'])
        data['filters'] = [ReportFilter(**f) for f in data['filters']]
        return ScheduledReport(**data)

    @staticmethod
    def _decode_execution(payload):
        data = dict(payload)
        if data['result']:
            data['result'] = GeneratedReport(**data['result'])
        return ReportExecution(**data)

    # ===== Template Management =====
    
    def create_template(
        self,
        name: str,
        report_type: ReportType,
        columns: List[Dict],
        description: str = '',
        default_filters: Optional[List[Dict]] = None,
        grouping: Optional[List[str]] = None,
        sorting: Optional[List[Dict]] = None,
        summary_fields: Optional[List[str]] = None,
        is_public: bool = False,
        created_by: str = 'system'
    ) -> ReportTemplate:
        """
        יצירת תבנית דוח
        Create Report Template
        """
        import uuid
        
        report_type = ReportType(report_type)
        template = ReportTemplate(
            template_id=f'TPL-{uuid.uuid4().hex.upper()}',
            name=name,
            description=description,
            report_type=report_type,
            columns=[
                ReportColumn(**col) if isinstance(col, dict) else col
                for col in columns
            ],
            default_filters=[
                ReportFilter(**f) if isinstance(f, dict) else f
                for f in (default_filters or [])
            ],
            grouping=grouping or [],
            sorting=sorting or [],
            summary_fields=summary_fields or [],
            created_by=created_by,
            created_at=datetime.now().isoformat(),
            is_public=is_public,
            organization_id=self.organization_id
        )
        
        self._templates[template.template_id] = template
        return template
    
    def get_templates(
        self,
        report_type: Optional[ReportType] = None,
        include_public: bool = True
    ) -> List[ReportTemplate]:
        """
        קבלת תבניות
        Get Templates
        """
        templates = list(self._templates.values()) + list(self._default_templates.values())
        
        # סינון לפי סוג
        if report_type:
            templates = [t for t in templates if t.report_type == report_type]
        
        # סינון לפי ציבורי/פרטי
        if not include_public:
            templates = [t for t in templates if t.organization_id == self.organization_id]
        
        return templates
    
    def get_template(self, template_id: str) -> Optional[ReportTemplate]:
        """קבלת תבנית לפי ID"""
        return self._templates.get(template_id) or self._default_templates.get(template_id)
    
    def update_template(self, template_id: str, updates: Dict) -> Optional[ReportTemplate]:
        """עדכון תבנית"""
        template = self._templates.get(template_id)
        if not template:
            return None
        
        allowed = {'name', 'description', 'columns', 'default_filters', 'grouping', 'sorting', 'summary_fields', 'is_public'}
        if set(updates) - allowed:
            raise ValueError('Immutable or unsupported report template field')
        data = dict(asdict(template), **updates)
        template = self._decode_template(data)
        self._templates[template_id] = template
        return template
    
    def delete_template(self, template_id: str) -> bool:
        """מחיקת תבנית"""
        if template_id in self._templates:
            del self._templates[template_id]
            return True
        return False
    
    # ===== Report Generation =====
    
    def generate_report(self, template_id: str, format: ReportFormat = ReportFormat.EXCEL,
                        filters=None, parameters=None, generated_by='system') -> GeneratedReport:
        import uuid
        if generated_by.startswith('schedule:'):
            return self._generate_report(template_id, format, filters, parameters, generated_by)
        execution = ReportExecution(f'EXC-{uuid.uuid4().hex}', None, template_id, 'running',
            datetime.now().isoformat(), None, None, None)
        self._executions[execution.execution_id] = execution
        try:
            report = self._generate_report(template_id, format, filters, parameters, generated_by)
            execution.status, execution.result = 'completed', report
            return report
        except Exception as exc:
            self.db.rollback()
            execution.status, execution.error_message = 'failed', str(exc)
            raise
        finally:
            execution.completed_at = datetime.now().isoformat()
            self._executions[execution.execution_id] = execution

    def _generate_report(
        self,
        template_id: str,
        format: ReportFormat = ReportFormat.EXCEL,
        filters: Optional[List[Dict]] = None,
        parameters: Optional[Dict] = None,
        generated_by: str = 'system'
    ) -> GeneratedReport:
        """
        יצירת דוח
        Generate Report
        """
        import time
        import uuid
        
        start_time = time.time()
        
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"תבנית {template_id} לא נמצאה")
        
        if format not in (ReportFormat.EXCEL, ReportFormat.CSV, ReportFormat.JSON, ReportFormat.HTML):
            raise ValueError('Report output format is not implemented')
        # מיזוג פילטרים
        all_filters = list(template.default_filters)
        if filters:
            all_filters.extend([
                ReportFilter(**f) if isinstance(f, dict) else f
                for f in filters
            ])
        
        # הרצת הדוח לפי סוג
        data = self._execute_report_query(template, all_filters, parameters)
        
        # יצירת הקובץ
        report_id = f'RPT-{uuid.uuid4().hex.upper()}'
        filename = f"{report_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if format == ReportFormat.EXCEL:
            file_path = self._generate_excel(filename, template, data)
        elif format == ReportFormat.CSV:
            file_path = self._generate_csv(filename, template, data)
        elif format == ReportFormat.JSON:
            file_path = self._generate_json(filename, template, data)
        elif format == ReportFormat.HTML:
            file_path = self._generate_html(filename, template, data)
        else:
            file_path = self._generate_json(filename, template, data)
        
        generation_time = int((time.time() - start_time) * 1000)
        
        report = GeneratedReport(
            report_id=report_id,
            template_id=template_id,
            generated_at=datetime.now().isoformat(),
            format=format,
            file_path=str(file_path) if file_path else None,
            file_size=file_path.stat().st_size if file_path and file_path.exists() else 0,
            row_count=len(data),
            generation_time_ms=generation_time,
            filters_applied=[asdict(f) if hasattr(f, '__dataclass_fields__') else f for f in all_filters],
            generated_by=generated_by,
            expires_at=(datetime.now() + timedelta(days=7)).isoformat(),
            download_url=f'/api/financial/reports/files/{report_id}' if file_path else None
        )
    
        import base64
        import hashlib
        content = file_path.read_bytes()
        self._files[report_id] = {'report': asdict(report),
            'content_base64': base64.b64encode(content).decode('ascii'),
            'sha256': hashlib.sha256(content).hexdigest(), 'parameters': parameters or {},
            'organization_id': self.organization_id, 'derived': True,
            'official_books_verified': False, 'source_completeness': 'not_verified'}
        return report

    def preview_report(
        self,
        template_id: str,
        filters: Optional[List[Dict]] = None,
        parameters: Optional[Dict] = None,
        limit: int = 100
    ) -> Dict:
        """
        תצוגה מקדימה של דוח
        Preview Report
        """
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"תבנית {template_id} לא נמצאה")
        
        all_filters = list(template.default_filters)
        if filters:
            all_filters.extend([
                ReportFilter(**f) if isinstance(f, dict) else f
                for f in filters
            ])
        
        data = self._execute_report_query(template, all_filters, parameters)
        
        # חישוב סיכומים
        summary = {}
        for field in template.summary_fields:
            values = [row.get(field, 0) for row in data if isinstance(row.get(field), (int, float))]
            if values:
                summary[field] = {
                    'sum': sum(values),
                    'avg': sum(values) / len(values),
                    'min': min(values),
                    'max': max(values),
                    'count': len(values)
                }
        
        return {
            'template': asdict(template),
            'data': data[:limit],
            'total_rows': len(data),
            'summary': summary,
            'preview_limited': len(data) > limit
        }
    
    # ===== Scheduling =====
    
    def create_schedule(
        self,
        template_id: str,
        name: str,
        frequency: ReportFrequency,
        recipients: List[str],
        delivery_method: DeliveryMethod = DeliveryMethod.EMAIL,
        format: ReportFormat = ReportFormat.EXCEL,
        filters: Optional[List[Dict]] = None,
        parameters: Optional[Dict] = None,
        created_by: str = 'system'
    ) -> ScheduledReport:
        """
        יצירת תזמון דוח
        Create Report Schedule
        """
        import uuid
        
        if self.get_template(template_id) is None:
            raise ValueError('Report template not found in this organization')
        if DeliveryMethod(delivery_method) != DeliveryMethod.DOWNLOAD:
            raise ValueError('Only saved-download delivery is implemented; external delivery is not verified')
        schedule = ScheduledReport(
            schedule_id=f'SCH-{uuid.uuid4().hex.upper()}',
            template_id=template_id,
            name=name,
            frequency=frequency,
            next_run=self._calculate_next_run(frequency),
            last_run=None,
            recipients=recipients,
            delivery_method=delivery_method,
            format=format,
            filters=[
                ReportFilter(**f) if isinstance(f, dict) else f
                for f in (filters or [])
            ],
            is_active=True,
            created_by=created_by,
            organization_id=self.organization_id,
            parameters=parameters or {}
        )
        
        self._schedules[schedule.schedule_id] = schedule
        return schedule
    
    def get_schedules(
        self,
        template_id: Optional[str] = None,
        active_only: bool = False
    ) -> List[ScheduledReport]:
        """
        קבלת תזמונים
        Get Schedules
        """
        schedules = list(self._schedules.values())
        
        if template_id:
            schedules = [s for s in schedules if s.template_id == template_id]
        
        if active_only:
            schedules = [s for s in schedules if s.is_active]
        
        return schedules
    
    def update_schedule(self, schedule_id: str, updates: Dict) -> Optional[ScheduledReport]:
        """עדכון תזמון"""
        schedule = self._schedules.get(schedule_id)
        if not schedule:
            return None
        
        if set(updates) - {'name', 'frequency', 'next_run', 'filters', 'parameters', 'is_active'}:
            raise ValueError('Immutable or unsupported report schedule field')
        for key, value in updates.items():
            if hasattr(schedule, key):
                if key == 'frequency':
                    setattr(schedule, key, ReportFrequency(value))
                    schedule.next_run = self._calculate_next_run(schedule.frequency)
                else:
                    setattr(schedule, key, value)
        
        schedule = self._decode_schedule(asdict(schedule))
        self._schedules[schedule_id] = schedule
        return schedule
    
    def delete_schedule(self, schedule_id: str) -> bool:
        """מחיקת תזמון"""
        if schedule_id in self._schedules:
            del self._schedules[schedule_id]
            return True
        return False
    
    def pause_schedule(self, schedule_id: str) -> bool:
        """השהיית תזמון"""
        schedule = self._schedules.get(schedule_id)
        if schedule:
            schedule.is_active = False
            self._schedules[schedule_id] = schedule
            return True
        return False
    
    def resume_schedule(self, schedule_id: str) -> bool:
        """חידוש תזמון"""
        schedule = self._schedules.get(schedule_id)
        if schedule:
            schedule.is_active = True
            schedule.next_run = self._calculate_next_run(schedule.frequency)
            self._schedules[schedule_id] = schedule
            return True
        return False
    
    # ===== Execution =====
    
    async def run_scheduled_reports(self) -> List[ReportExecution]:
        """Claim each due occurrence durably before generation; no silent catch-up."""
        from sqlalchemy.exc import IntegrityError
        from ..models import ReportRecord
        now = datetime.now()
        executions = []
        for schedule in list(self._schedules.values()):
            if not schedule.is_active or datetime.fromisoformat(schedule.next_run) > now:
                continue
            occurrence = f'{schedule.schedule_id}:{schedule.next_run}'
            execution = ReportExecution(occurrence, schedule.schedule_id, schedule.template_id,
                'running', now.isoformat(), None, None, None)
            # Concurrent workers share the unique organization/kind/reference claim.
            try:
                with self.db.begin_nested():
                    self.db.add(ReportRecord(organization_id=self.organization_id, kind='execution',
                        reference=occurrence, payload=asdict(execution), version=1, deleted=False))
                    self.db.flush()
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                continue
            try:
                # Re-read after claiming, so a paused or modified schedule does not execute.
                current = self._schedules[schedule.schedule_id]
                if not current.is_active or current.version != schedule.version:
                    raise ValueError('Schedule changed after the occurrence was claimed')
                if current.delivery_method != DeliveryMethod.DOWNLOAD:
                    raise ValueError('External report delivery is not implemented')
                report = self.generate_report(template_id=schedule.template_id, format=schedule.format,
                    filters=[asdict(f) for f in schedule.filters], parameters=schedule.parameters,
                    generated_by=f'schedule:{schedule.schedule_id}')
                execution.status, execution.result = 'completed', report
                current.last_run = datetime.now().isoformat()
                current.next_run = self._calculate_next_run(current.frequency)
                if current.frequency == ReportFrequency.ON_DEMAND:
                    current.is_active = False
                self._schedules[current.schedule_id] = current
            except Exception as exc:
                self.db.rollback()
                execution.status, execution.error_message = 'failed', str(exc)
                # Existing occurrence claim prevents replay. Do not overwrite an operator's newer decision.
            execution.completed_at = datetime.now().isoformat()
            self._executions[occurrence] = execution
            executions.append(execution)
        return executions

    def get_execution_history(
        self,
        schedule_id: Optional[str] = None,
        template_id: Optional[str] = None,
        limit: int = 50
    ) -> List[ReportExecution]:
        """
        היסטוריית ביצועים
        Execution History
        """
        executions = list(self._executions.values())
        
        if schedule_id:
            executions = [e for e in executions if e.schedule_id == schedule_id]
        
        if template_id:
            executions = [e for e in executions if e.template_id == template_id]
        
        # מיון לפי תאריך (חדש ראשון)
        executions = sorted(executions, key=lambda x: x.started_at, reverse=True)
        
        return executions[:limit]
    
    # ===== Private Methods =====
    
    def _create_default_templates(self) -> Dict[str, ReportTemplate]:
        """יצירת תבניות ברירת מחדל"""
        templates = {}
        
        # תבנית רווח והפסד
        templates['DEFAULT-PL'] = ReportTemplate(
            template_id='DEFAULT-PL',
            name='דוח רווח והפסד',
            description='דוח רווח והפסד חודשי/שנתי',
            report_type=ReportType.PROFIT_LOSS,
            columns=[
                ReportColumn('category', 'קטגוריה', 'string', 200),
                ReportColumn('amount', 'סכום', 'currency', 120, '₪#,##0'),
                ReportColumn('budget', 'תקציב', 'currency', 120, '₪#,##0'),
                ReportColumn('variance', 'סטייה', 'percentage', 100, '0.0%'),
                ReportColumn('previous_period', 'תקופה קודמת', 'currency', 120, '₪#,##0'),
            ],
            default_filters=[],
            grouping=['category'],
            sorting=[{'field': 'amount', 'direction': 'desc'}],
            summary_fields=['amount', 'budget'],
            created_by='system',
            created_at=datetime.now().isoformat(),
            is_public=True,
            organization_id=0
        )
        
        # תבנית גיול חובות
        templates['DEFAULT-AGING'] = ReportTemplate(
            template_id='DEFAULT-AGING',
            name='דוח גיול חובות',
            description='דוח גיול חובות לקוחות',
            report_type=ReportType.AGING_REPORT,
            columns=[
                ReportColumn('customer_name', 'לקוח', 'string', 200),
                ReportColumn('current', 'שוטף', 'currency', 100, '₪#,##0'),
                ReportColumn('days_31_60', '31-60 יום', 'currency', 100, '₪#,##0'),
                ReportColumn('days_61_90', '61-90 יום', 'currency', 100, '₪#,##0'),
                ReportColumn('days_91_120', '91-120 יום', 'currency', 100, '₪#,##0'),
                ReportColumn('over_120', 'מעל 120', 'currency', 100, '₪#,##0'),
                ReportColumn('total', 'סה"כ', 'currency', 120, '₪#,##0'),
            ],
            default_filters=[],
            grouping=[],
            sorting=[{'field': 'total', 'direction': 'desc'}],
            summary_fields=['current', 'days_31_60', 'days_61_90', 'days_91_120', 'over_120', 'total'],
            created_by='system',
            created_at=datetime.now().isoformat(),
            is_public=True,
            organization_id=0
        )
        
        # תבנית KPI
        templates['DEFAULT-KPI'] = ReportTemplate(
            template_id='DEFAULT-KPI',
            name='דשבורד KPI',
            description='סיכום מדדי ביצוע מרכזיים',
            report_type=ReportType.KPI_DASHBOARD,
            columns=[
                ReportColumn('kpi_name', 'מדד', 'string', 200),
                ReportColumn('value', 'ערך', 'number', 100),
                ReportColumn('target', 'יעד', 'number', 100),
                ReportColumn('status', 'סטטוס', 'string', 80),
                ReportColumn('trend', 'מגמה', 'string', 80),
            ],
            default_filters=[],
            grouping=['category'],
            sorting=[{'field': 'category', 'direction': 'asc'}],
            summary_fields=[],
            created_by='system',
            created_at=datetime.now().isoformat(),
            is_public=True,
            organization_id=0
        )
        
        return templates
    
    def _execute_report_query(
        self,
        template: ReportTemplate,
        filters: List[ReportFilter],
        parameters: Optional[Dict]
    ) -> List[Dict]:
        """ביצוע שאילתת הדוח — מקור אמת: השירותים הפיננסיים האמיתיים (org-scoped)."""
        generators = {ReportType.PROFIT_LOSS: self._generate_pl_data,
            ReportType.AGING_REPORT: self._generate_aging_data,
            ReportType.KPI_DASHBOARD: self._generate_kpi_data,
            ReportType.BUDGET_VS_ACTUAL: self._generate_budget_data}
        if template.report_type not in generators:
            raise ValueError('This report type is not implemented by the saved-report adapter')
        fields = {c.field_name for c in template.columns}
        for filter in filters:
            if filter.field_name not in fields or filter.operator not in ('eq', 'ne', 'gte', 'lte'):
                raise ValueError('Unsupported report filter field or operator')
        data = generators[template.report_type](parameters)
        for filter in filters:
            def keep(row):
                value = row.get(filter.field_name)
                if value is None: return False
                if filter.operator == 'eq': return value == filter.value
                if filter.operator == 'ne': return value != filter.value
                if filter.operator == 'gte': return value >= filter.value
                return value <= filter.value
            try:
                data = [row for row in data if keep(row)]
            except TypeError as exc:
                raise ValueError('Filter value does not match report field type') from exc
        for ordering in reversed(template.sorting):
            field = ordering.get('field')
            if field not in fields and not all(field in row for row in data):
                raise ValueError('Unsupported report sort field')
            data.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=ordering.get('direction') == 'desc')
        return data

    @staticmethod
    def _period_from(parameters: Optional[Dict]) -> tuple:
        """(year, month) מהפרמטרים, עם ברירת מחדל לחודש הנוכחי."""
        p = parameters or {}
        today = date.today()
        return int(p.get('year', today.year)), int(p.get('month', today.month))

    def _generate_pl_data(self, parameters: Optional[Dict] = None) -> List[Dict]:
        """נתוני רווח והפסד אמיתיים מ-FinancialReportsService (נטו, מ-ledger)."""
        from .financial_reports_service import FinancialReportsService
        year, month = self._period_from(parameters)
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
        try:
            rep = FinancialReportsService(self.db).generate_profit_loss(
                self.organization_id, start, end, compare_previous=True)
        except Exception:
            logger.exception("report_builder P&L failed for org %s", self.organization_id)
            raise ValueError("Report source unavailable; no successful empty report was produced")

        sections = [
            ('הכנסות', rep.revenue), ('עלות המכר', rep.cost_of_goods_sold),
            ('הוצאות תפעול', rep.operating_expenses),
            ('הכנסות אחרות', rep.other_income), ('הוצאות אחרות', rep.other_expenses),
        ]
        rows = []
        for section, items in sections:
            for it in items:
                rows.append({
                    'category': section,
                    'subcategory': it.category_hebrew,
                    'amount': it.amount,
                    'budget': None,  # Prior actuals are not an approved budget.
                    'variance': it.change_percentage,
                    'previous_period': it.previous_amount,
                })
        return rows

    def _generate_aging_data(self, parameters: Optional[Dict] = None) -> List[Dict]:
        """נתוני גיול חובות אמיתיים מ-AccountsReceivableService."""
        from .ar_service import AccountsReceivableService
        try:
            rep = AccountsReceivableService(self.db, self.organization_id).get_aging_report()
        except Exception:
            logger.exception("report_builder aging failed for org %s", self.organization_id)
            raise ValueError("Report source unavailable; no successful empty report was produced")
        return [{
            'customer_name': c.customer_name,
            'current': c.current,
            'days_31_60': c.days_31_60,
            'days_61_90': c.days_61_90,
            'days_91_120': c.days_91_120,
            'over_120': c.over_120,
            'total': c.total_outstanding,
        } for c in rep.customers]

    def _generate_kpi_data(self, parameters: Optional[Dict] = None) -> List[Dict]:
        """נתוני KPI אמיתיים מ-KPIService."""
        from .kpi_service import KPIService
        try:
            dash = KPIService(self.db, self.organization_id).get_kpi_dashboard()
        except Exception:
            logger.exception("report_builder KPI failed for org %s", self.organization_id)
            raise ValueError("Report source unavailable; no successful empty report was produced")
        return [{
            'category': k.category.value if hasattr(k.category, 'value') else str(k.category),
            'kpi_name': k.name_hebrew or k.name,
            'value': k.value,
            'target': k.target,
            'status': k.status.value if hasattr(k.status, 'value') else str(k.status),
            'trend': k.trend.value if hasattr(k.trend, 'value') else str(k.trend),
        } for k in dash.kpis]

    def _generate_budget_data(self, parameters: Optional[Dict] = None) -> List[Dict]:
        """נתוני תקציב מול ביצוע אמיתיים מ-BudgetService."""
        from .budget_service import BudgetService
        year, month = self._period_from(parameters)
        try:
            summary = BudgetService(self.db, self.organization_id).get_budget_vs_actual(year, month)
        except Exception:
            logger.exception("report_builder budget failed for org %s", self.organization_id)
            raise ValueError("Report source unavailable; no successful empty report was produced")
        return [{
            'category': c.category_hebrew,
            'budget': c.budget_amount,
            'actual': c.actual_amount,
            'variance': c.variance,
            'variance_pct': c.variance_percentage,
        } for c in summary.categories]
    
    def _generate_excel(self, filename: str, template: ReportTemplate, data: List[Dict]) -> Path:
        """יצירת קובץ Excel"""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Fill, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
        except ImportError:
            return self._generate_csv(filename, template, data)
        
        wb = Workbook()
        ws = wb.active
        ws.title = template.name[:31]  # Excel limit
        
        # RTL
        ws.sheet_view.rightToLeft = True
        
        # כותרת
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(template.columns))
        ws['A1'] = template.name
        ws['A1'].font = Font(bold=True, size=16)
        ws['A1'].alignment = Alignment(horizontal='center')
        
        # תאריך יצירה
        ws['A2'] = f'תאריך הפקה: {datetime.now().strftime("%d/%m/%Y %H:%M")}'
        
        # כותרות עמודות
        header_row = 4
        header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF')
        
        for col_idx, col in enumerate(template.columns, 1):
            cell = ws.cell(row=header_row, column=col_idx, value=col.display_name)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')
            if col.width:
                ws.column_dimensions[get_column_letter(col_idx)].width = col.width / 7
        
        # נתונים
        for row_idx, row_data in enumerate(data, header_row + 1):
            for col_idx, col in enumerate(template.columns, 1):
                value = row_data.get(col.field_name, '')
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                
                if col.data_type == 'currency':
                    cell.number_format = '₪#,##0'
                elif col.data_type == 'percentage':
                    cell.number_format = '0.0%'
                    if isinstance(value, (int, float)):
                        cell.value = value / 100
        
        # שמירה
        file_path = self.reports_dir / f'{filename}.xlsx'
        wb.save(file_path)
        
        return file_path
    
    def _generate_csv(self, filename: str, template: ReportTemplate, data: List[Dict]) -> Path:
        """יצירת קובץ CSV"""
        import csv
        
        file_path = self.reports_dir / f'{filename}.csv'
        
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            
            # כותרות
            headers = [col.display_name for col in template.columns]
            writer.writerow(headers)
            
            # נתונים
            for row in data:
                row_values = [row.get(col.field_name, '') for col in template.columns]
                writer.writerow(row_values)
        
        return file_path
    
    def _generate_json(self, filename: str, template: ReportTemplate, data: List[Dict]) -> Path:
        """יצירת קובץ JSON"""
        file_path = self.reports_dir / f'{filename}.json'
        
        output = {
            'template': asdict(template),
            'generated_at': datetime.now().isoformat(),
            'data': data,
            'row_count': len(data)
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        return file_path
    
    def _generate_html(self, filename: str, template: ReportTemplate, data: List[Dict]) -> Path:
        """יצירת קובץ HTML"""
        from html import escape
        file_path = self.reports_dir / f'{filename}.html'
        
        html = f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
    <meta charset="UTF-8">
    <title>{escape(template.name)}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; direction: rtl; }}
        h1 {{ color: #366092; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th {{ background-color: #366092; color: white; padding: 12px; text-align: right; }}
        td {{ border: 1px solid #ddd; padding: 10px; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .meta {{ color: #666; margin-bottom: 20px; }}
        .currency {{ text-align: left; }}
        .number {{ text-align: left; }}
    </style>
</head>
<body>
    <h1>{escape(template.name)}</h1>
    <p class="meta">תאריך הפקה: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
    <table>
        <thead>
            <tr>
                {''.join(f'<th>{escape(col.display_name)}</th>' for col in template.columns)}
            </tr>
        </thead>
        <tbody>
"""
        
        for row in data:
            html += '<tr>'
            for col in template.columns:
                value = row.get(col.field_name, '')
                if col.data_type == 'currency' and isinstance(value, (int, float)):
                    value = f'₪{value:,.0f}'
                elif col.data_type == 'percentage' and isinstance(value, (int, float)):
                    value = f'{value:.1f}%'
                html += f'<td class="{escape(col.data_type, quote=True)}">{escape(str(value))}</td>'
            html += '</tr>\n'
        
        html += """
        </tbody>
    </table>
</body>
</html>
"""
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        return file_path
    
    def _calculate_next_run(self, frequency: ReportFrequency) -> str:
        """חישוב הרצה הבאה"""
        now = datetime.now()
        
        if frequency == ReportFrequency.DAILY:
            next_run = now + timedelta(days=1)
            next_run = next_run.replace(hour=6, minute=0, second=0, microsecond=0)
        elif frequency == ReportFrequency.WEEKLY:
            days_until_sunday = (6 - now.weekday()) % 7 or 7
            next_run = now + timedelta(days=days_until_sunday)
            next_run = next_run.replace(hour=6, minute=0, second=0, microsecond=0)
        elif frequency == ReportFrequency.MONTHLY:
            if now.month == 12:
                next_run = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_run = now.replace(month=now.month + 1, day=1)
            next_run = next_run.replace(hour=6, minute=0, second=0, microsecond=0)
        elif frequency == ReportFrequency.QUARTERLY:
            current_quarter = (now.month - 1) // 3 + 1
            next_quarter_month = ((current_quarter % 4) * 3) + 1
            if next_quarter_month <= now.month:
                next_run = now.replace(year=now.year + 1, month=next_quarter_month, day=1)
            else:
                next_run = now.replace(month=next_quarter_month, day=1)
            next_run = next_run.replace(hour=6, minute=0, second=0, microsecond=0)
        elif frequency == ReportFrequency.YEARLY:
            next_run = now.replace(year=now.year + 1, month=1, day=1, hour=6, minute=0, second=0, microsecond=0)
        else:
            next_run = now
        
        return next_run.isoformat()
    
    async def _deliver_report(self, schedule: ScheduledReport, report: GeneratedReport):
        """משלוח הדוח"""
        if schedule.delivery_method == DeliveryMethod.EMAIL:
            await self._send_email(schedule.recipients, report)
        elif schedule.delivery_method == DeliveryMethod.WEBHOOK:
            await self._send_webhook(schedule.parameters.get('webhook_url'), report)
        # שאר שיטות המשלוח...
    
    async def _send_email(self, recipients: List[str], report: GeneratedReport):
        """שליחת מייל"""
        raise ValueError('Scheduled email delivery is not implemented')
    
    async def _send_webhook(self, url: str, report: GeneratedReport):
        """שליחת webhook"""
        raise ValueError('Scheduled webhook delivery is not implemented')
