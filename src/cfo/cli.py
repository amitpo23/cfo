"""
Main CLI entry point for CFO system
"""
import click
import asyncio
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from datetime import datetime, timedelta

from .config import settings
from .database import init_db, SessionLocal
from .integrations.sumit_integration import SumitIntegration
from .services.sumit_request_budget import SumitRequestLimiter

console = Console()


@click.group()
def cli():
    """CFO Financial Management System CLI"""
    pass


@cli.command()
def init():
    """Initialize the database"""
    console.print("🗄️  Initializing database...", style="bold blue")
    init_db()
    console.print("✅ Database initialized successfully!", style="bold green")


@cli.command()
def test_sumit():
    """Test SUMIT API connection"""
    console.print("🔌 Testing SUMIT API connection...", style="bold blue")
    
    if not settings.sumit_api_key:
        console.print("❌ SUMIT_API_KEY not configured!", style="bold red")
        return
    
    async def test():
        async with SumitIntegration(
            api_key=settings.sumit_api_key,
            company_id=settings.sumit_company_id,
            request_limiter=SumitRequestLimiter(1),
        ) as sumit:
            is_connected = await sumit.test_connection()
            if is_connected:
                console.print("✅ Successfully connected to SUMIT API!", style="bold green")
                
                # Get balance
                try:
                    balance = await sumit.get_balance()
                    console.print("\n💰 Account Balance:", style="bold")
                    console.print(balance)
                except Exception as e:
                    console.print(f"⚠️  Could not fetch balance: {e}", style="yellow")
            else:
                console.print("❌ Failed to connect to SUMIT API", style="bold red")
    
    asyncio.run(test())


@cli.command()
def run():
    """Run the FastAPI server"""
    import uvicorn
    from .api import app
    
    console.print("🚀 Starting CFO API server...", style="bold blue")
    console.print(f"📍 API Docs: http://localhost:8000/api/docs", style="cyan")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )


@cli.command()
def config():
    """Show current configuration"""
    table = Table(title="CFO System Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("App Name", settings.app_name)
    table.add_row("Debug Mode", str(settings.debug))
    table.add_row("Log Level", settings.log_level)
    table.add_row("Database", settings.database_url)
    table.add_row("Timezone", settings.timezone)
    table.add_row("SUMIT API Configured", "Yes" if settings.sumit_api_key else "No")
    table.add_row("OpenAI Configured", "Yes" if settings.openai_api_key else "No")
    
    console.print(table)


# ============= Cash Flow Commands =============

@cli.group()
def cashflow():
    """Cash flow management commands"""
    pass


@cashflow.command("summary")
@click.option("--months", default=3, help="Number of months to analyze")
def cashflow_summary(months: int):
    """Show cash flow summary"""
    from .services.cash_flow_service import CashFlowService
    
    db = SessionLocal()
    try:
        service = CashFlowService(db)
        
        # קבלת נתונים חודשיים
        data = service.get_monthly_cash_flow(organization_id=1, months=months)
        
        # יצירת טבלה
        table = Table(title=f"תזרים מזומנים - {months} חודשים אחרונים")
        table.add_column("חודש", style="cyan")
        table.add_column("כניסות", style="green", justify="right")
        table.add_column("יציאות", style="red", justify="right")
        table.add_column("נטו", justify="right")
        table.add_column("מצטבר", style="blue", justify="right")
        
        for row in data:
            net_style = "green" if row['net_flow'] >= 0 else "red"
            table.add_row(
                row['month'],
                f"₪{row['inflows']:,.0f}",
                f"₪{row['outflows']:,.0f}",
                f"[{net_style}]₪{row['net_flow']:,.0f}[/{net_style}]",
                f"₪{row['cumulative']:,.0f}"
            )
        
        console.print(table)
        
    finally:
        db.close()


@cashflow.command("burn-rate")
@click.option("--months", default=3, help="Analysis period in months")
def cashflow_burn_rate(months: int):
    """Calculate cash burn rate"""
    from .services.cash_flow_service import CashFlowService
    
    db = SessionLocal()
    try:
        service = CashFlowService(db)
        data = service.get_cash_burn_rate(organization_id=1, months=months)
        
        panel_content = f"""
[bold]הוצאות חודשיות ממוצעות:[/bold] ₪{data['monthly_burn_rate']:,.0f}
[bold]הכנסות חודשיות ממוצעות:[/bold] ₪{data['monthly_income']:,.0f}
[bold]שריפה נטו חודשית:[/bold] ₪{data['net_monthly_burn']:,.0f}
[bold]יתרה נוכחית:[/bold] ₪{data['current_balance']:,.0f}
[bold]Runway:[/bold] {"∞" if data['runway_months'] == float('inf') else f"{data['runway_months']:.1f} חודשים"}
        """
        
        panel = Panel(panel_content.strip(), title="ניתוח קצב שריפה", border_style="blue")
        console.print(panel)
        
        if data['net_monthly_burn'] > 0 and data['runway_months'] < 12:
            console.print("\n⚠️  [yellow]אזהרה: Runway קצר מ-12 חודשים![/yellow]")
        
    finally:
        db.close()


@cashflow.command("ratios")
def cashflow_ratios():
    """Show liquidity ratios"""
    from .services.cash_flow_service import CashFlowService
    
    db = SessionLocal()
    try:
        service = CashFlowService(db)
        data = service.get_liquidity_ratios(organization_id=1)
        
        table = Table(title="יחסי נזילות")
        table.add_column("יחס", style="cyan")
        table.add_column("ערך", justify="right")
        table.add_column("סטטוס")
        
        # יחס שוטף
        current_status = "✅ תקין" if data['current_ratio'] >= 1.5 else "⚠️ נמוך"
        table.add_row("יחס שוטף", f"{data['current_ratio']:.2f}", current_status)
        
        # יחס מהיר
        quick_status = "✅ תקין" if data['quick_ratio'] >= 1.0 else "⚠️ נמוך"
        table.add_row("יחס מהיר", f"{data['quick_ratio']:.2f}", quick_status)
        
        # יחס מזומנים
        cash_status = "✅ תקין" if data['cash_ratio'] >= 0.5 else "⚠️ נמוך"
        table.add_row("יחס מזומנים", f"{data['cash_ratio']:.2f}", cash_status)
        
        table.add_row("הון חוזר", f"₪{data['working_capital']:,.0f}", "")
        table.add_row("נכסים שוטפים", f"₪{data['current_assets']:,.0f}", "")
        table.add_row("התחייבויות שוטפות", f"₪{data['current_liabilities']:,.0f}", "")
        
        console.print(table)
        
    finally:
        db.close()


# ============= Forecasting Commands =============

@cli.group()
def forecast():
    """Financial forecasting commands"""
    pass


@forecast.command("revenue")
@click.option("--periods", default=12, help="Forecast periods (months)")
@click.option("--method", default="exponential_smoothing", 
              type=click.Choice(['exponential_smoothing', 'moving_average', 'linear_regression', 'seasonal', 'ensemble']),
              help="Forecasting method")
def forecast_revenue(periods: int, method: str):
    """Forecast revenue"""
    from .services.forecasting_service import ForecastingService, ForecastMethod
    
    db = SessionLocal()
    try:
        service = ForecastingService(db)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מחשב תחזית הכנסות...", total=None)
            results = service.forecast_revenue(
                organization_id=1,
                periods=periods,
                method=ForecastMethod(method)
            )
        
        table = Table(title=f"תחזית הכנסות - {periods} חודשים ({method})")
        table.add_column("תקופה", style="cyan")
        table.add_column("תחזית", style="green", justify="right")
        table.add_column("טווח תחתון", justify="right")
        table.add_column("טווח עליון", justify="right")
        table.add_column("ביטחון", justify="right")
        
        for r in results:
            table.add_row(
                r.date.strftime('%Y-%m'),
                f"₪{r.predicted_value:,.0f}",
                f"₪{r.lower_bound:,.0f}",
                f"₪{r.upper_bound:,.0f}",
                f"{r.confidence*100:.0f}%"
            )
        
        console.print(table)
        
    finally:
        db.close()


@forecast.command("expenses")
@click.option("--periods", default=12, help="Forecast periods (months)")
def forecast_expenses(periods: int):
    """Forecast expenses"""
    from .services.forecasting_service import ForecastingService
    
    db = SessionLocal()
    try:
        service = ForecastingService(db)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מחשב תחזית הוצאות...", total=None)
            results = service.forecast_expenses(organization_id=1, periods=periods)
        
        table = Table(title=f"תחזית הוצאות - {periods} חודשים")
        table.add_column("תקופה", style="cyan")
        table.add_column("תחזית", style="red", justify="right")
        table.add_column("טווח תחתון", justify="right")
        table.add_column("טווח עליון", justify="right")
        
        for r in results:
            table.add_row(
                r.date.strftime('%Y-%m'),
                f"₪{r.predicted_value:,.0f}",
                f"₪{r.lower_bound:,.0f}",
                f"₪{r.upper_bound:,.0f}"
            )
        
        console.print(table)
        
    finally:
        db.close()


@forecast.command("cashflow")
@click.option("--periods", default=12, help="Forecast periods (months)")
@click.option("--balance", default=0, help="Current cash balance")
def forecast_cashflow(periods: int, balance: float):
    """Forecast cash flow"""
    from .services.forecasting_service import ForecastingService
    
    db = SessionLocal()
    try:
        service = ForecastingService(db)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מחשב תחזית תזרים מזומנים...", total=None)
            results = service.forecast_cash_flow(
                organization_id=1,
                periods=periods,
                current_balance=balance
            )
        
        table = Table(title=f"תחזית תזרים מזומנים - {periods} חודשים")
        table.add_column("תקופה", style="cyan")
        table.add_column("כניסות", style="green", justify="right")
        table.add_column("יציאות", style="red", justify="right")
        table.add_column("נטו", justify="right")
        table.add_column("יתרה", style="blue", justify="right")
        
        for r in results:
            net_style = "green" if r['projected_net_flow'] >= 0 else "red"
            balance_style = "green" if r['projected_balance'] >= 0 else "red"
            table.add_row(
                r['date'],
                f"₪{r['projected_inflows']:,.0f}",
                f"₪{r['projected_outflows']:,.0f}",
                f"[{net_style}]₪{r['projected_net_flow']:,.0f}[/{net_style}]",
                f"[{balance_style}]₪{r['projected_balance']:,.0f}[/{balance_style}]"
            )
        
        console.print(table)
        
    finally:
        db.close()


@forecast.command("trends")
@click.option("--months", default=12, help="Analysis period in months")
def forecast_trends(months: int):
    """Analyze financial trends"""
    from .services.forecasting_service import ForecastingService
    
    db = SessionLocal()
    try:
        service = ForecastingService(db)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מנתח מגמות...", total=None)
            trends = service.detect_trends(organization_id=1, months=months)
        
        # מגמת הכנסות
        revenue_panel = f"""
[bold]מגמה:[/bold] {_translate_trend(trends['revenue']['trend'])}
[bold]צמיחה:[/bold] {trends['revenue']['growth_rate']:.1f}%
[bold]ממוצע:[/bold] ₪{trends['revenue']['average']:,.0f}
[bold]תנודתיות:[/bold] ₪{trends['revenue']['volatility']:,.0f}
        """
        console.print(Panel(revenue_panel.strip(), title="📈 הכנסות", border_style="green"))
        
        # מגמת הוצאות
        expense_panel = f"""
[bold]מגמה:[/bold] {_translate_trend(trends['expenses']['trend'])}
[bold]צמיחה:[/bold] {trends['expenses']['growth_rate']:.1f}%
[bold]ממוצע:[/bold] ₪{trends['expenses']['average']:,.0f}
[bold]תנודתיות:[/bold] ₪{trends['expenses']['volatility']:,.0f}
        """
        console.print(Panel(expense_panel.strip(), title="📉 הוצאות", border_style="red"))
        
        # עונתיות
        if trends['seasonality']['detected']:
            season_panel = f"""
[bold]זוהתה עונתיות![/bold]
רבעון שיא: Q{trends['seasonality']['peak_quarter']}
רבעון שפל: Q{trends['seasonality']['low_quarter']}
            """
            console.print(Panel(season_panel.strip(), title="🗓️ עונתיות", border_style="blue"))
        
    finally:
        db.close()


@forecast.command("accuracy")
@click.option("--test-months", default=3, help="Test period in months")
def forecast_accuracy(test_months: int):
    """Evaluate forecast accuracy"""
    from .services.forecasting_service import ForecastingService
    
    db = SessionLocal()
    try:
        service = ForecastingService(db)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מחשב דיוק תחזית...", total=None)
            metrics = service.evaluate_forecast_accuracy(
                organization_id=1,
                test_months=test_months
            )
        
        table = Table(title="מטריקות דיוק תחזית")
        table.add_column("מטריקה", style="cyan")
        table.add_column("ערך", justify="right")
        table.add_column("הסבר")
        
        table.add_row("MAE", f"₪{metrics.mae:,.0f}", "שגיאה ממוצעת מוחלטת")
        table.add_row("MAPE", f"{metrics.mape:.1f}%", "שגיאה אחוזית ממוצעת")
        table.add_row("RMSE", f"₪{metrics.rmse:,.0f}", "שורש שגיאה ריבועית")
        table.add_row("R²", f"{metrics.r2:.3f}", "מקדם הסבר")
        
        console.print(table)
        
        accuracy = 100 - metrics.mape
        if accuracy >= 90:
            console.print(f"\n✅ [green]דיוק תחזית: {accuracy:.1f}% - מצוין![/green]")
        elif accuracy >= 80:
            console.print(f"\n✅ [yellow]דיוק תחזית: {accuracy:.1f}% - טוב[/yellow]")
        else:
            console.print(f"\n⚠️ [red]דיוק תחזית: {accuracy:.1f}% - דרוש שיפור[/red]")
        
    finally:
        db.close()


def _translate_trend(trend: str) -> str:
    """תרגום מגמה לעברית"""
    translations = {
        'increasing': '📈 עולה',
        'decreasing': '📉 יורד',
        'stable': '➡️ יציב',
        'insufficient_data': '❓ אין מספיק נתונים'
    }
    return translations.get(trend, trend)


# ============= Data Sync Commands =============

@cli.group()
def sync():
    """SUMIT data sync commands"""
    pass


@sync.command("documents")
@click.option("--days", default=90, help="Number of days to sync")
def sync_documents(days: int):
    """Sync documents from SUMIT"""
    from datetime import date, timedelta
    from .services.data_sync_service import DataSyncService
    
    db = SessionLocal()
    try:
        service = DataSyncService(db, organization_id=1)
        
        from_date = date.today() - timedelta(days=days)
        to_date = date.today()
        
        async def do_sync():
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                progress.add_task(description=f"מסנכרן מסמכים מ-SUMIT ({days} ימים)...", total=None)
                result = await service.sync_documents(from_date, to_date)
            return result
        
        result = asyncio.run(do_sync())
        
        if 'error' in result:
            console.print(f"❌ שגיאה: {result['error']}", style="bold red")
        else:
            console.print(f"✅ סונכרנו {result['synced_documents']} מסמכים!", style="bold green")
            console.print(f"   הכנסות: ₪{result['total_income']:,.0f}")
            console.print(f"   הוצאות: ₪{result['total_expenses']:,.0f}")
        
    finally:
        db.close()


@sync.command("payments")
@click.option("--days", default=90, help="Number of days to sync")
def sync_payments(days: int):
    """Sync payments from SUMIT"""
    from datetime import date, timedelta
    from .services.data_sync_service import DataSyncService
    
    db = SessionLocal()
    try:
        service = DataSyncService(db, organization_id=1)
        
        from_date = date.today() - timedelta(days=days)
        to_date = date.today()
        
        async def do_sync():
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                progress.add_task(description=f"מסנכרן תשלומים מ-SUMIT ({days} ימים)...", total=None)
                result = await service.sync_payments(from_date, to_date)
            return result
        
        result = asyncio.run(do_sync())
        
        if 'error' in result:
            console.print(f"❌ שגיאה: {result['error']}", style="bold red")
        else:
            console.print(f"✅ סונכרנו {result['synced_payments']} תשלומים!", style="bold green")
            console.print(f"   סה\"כ: ₪{result['total_amount']:,.0f}")
        
    finally:
        db.close()


@sync.command("all")
@click.option("--days", default=90, help="Number of days to sync")
def sync_all(days: int):
    """Full sync from SUMIT"""
    from datetime import date, timedelta
    from .services.data_sync_service import DataSyncService
    
    db = SessionLocal()
    try:
        service = DataSyncService(db, organization_id=1)
        
        from_date = date.today() - timedelta(days=days)
        to_date = date.today()
        
        async def do_sync():
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                progress.add_task(description="מבצע סנכרון מלא מ-SUMIT...", total=None)
                result = await service.sync_all(from_date, to_date)
            return result
        
        result = asyncio.run(do_sync())
        
        console.print("\n📊 [bold]תוצאות סנכרון מלא:[/bold]\n")
        
        if 'documents' in result and 'error' not in result['documents']:
            console.print(f"  📄 מסמכים: {result['documents'].get('synced_documents', 0)}")
        
        if 'payments' in result and 'error' not in result['payments']:
            console.print(f"  💳 תשלומים: {result['payments'].get('synced_payments', 0)}")
        
        if 'billing' in result and 'error' not in result['billing']:
            console.print(f"  💳 סליקה: {result['billing'].get('synced_billing_transactions', 0)}")
        
        if 'debts' in result and 'error' not in result['debts']:
            console.print(f"  📋 חובות: {result['debts'].get('count', 0)}")
        
        console.print("\n✅ [green]סנכרון הושלם![/green]")
        
    finally:
        db.close()


@sync.command("debts")
def sync_debts():
    """Show debt report from SUMIT"""
    from .services.data_sync_service import DataSyncService
    
    db = SessionLocal()
    try:
        service = DataSyncService(db, organization_id=1)
        
        async def get_debts():
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                progress.add_task(description="מושך דוח חובות מ-SUMIT...", total=None)
                result = await service.sync_debt_report()
            return result
        
        result = asyncio.run(get_debts())
        
        if 'error' in result:
            console.print(f"❌ שגיאה: {result['error']}", style="bold red")
        else:
            table = Table(title="דוח חובות מ-SUMIT")
            table.add_column("לקוח", style="cyan")
            table.add_column("סכום", justify="right")
            table.add_column("ימי פיגור", justify="center")
            
            for item in result.get('debt_items', [])[:20]:
                amount_style = "green" if item['amount'] > 0 else "red"
                table.add_row(
                    item['customer_name'],
                    f"[{amount_style}]₪{item['amount']:,.0f}[/{amount_style}]",
                    f"{item['days_overdue']}" if item['days_overdue'] > 0 else "-"
                )
            
            console.print(table)
            console.print(f"\n📈 לגבייה: ₪{result['total_receivable']:,.0f}")
            console.print(f"📉 לתשלום: ₪{result['total_payable']:,.0f}")
        
    finally:
        db.close()


# ============= Bank Statement Commands =============

@cli.group()
def bank():
    """Bank statement commands"""
    pass


@bank.command("import")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--format", "bank_format", default="auto", help="Bank format (auto/leumi/hapoalim/discount/mizrahi/isracard/cal/max)")
@click.option("--no-save", is_flag=True, help="Parse only without saving")
def bank_import(file_path: str, bank_format: str, no_save: bool):
    """Import bank statement from CSV/Excel file"""
    from .services.bank_statement_service import BankStatementService, BankFormat
    
    db = SessionLocal()
    try:
        service = BankStatementService(db, organization_id=1)
        
        # קריאת הקובץ
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # זיהוי סוג הקובץ
        file_type = 'excel' if file_path.lower().endswith(('.xlsx', '.xls')) else 'csv'
        
        try:
            format_enum = BankFormat(bank_format)
        except ValueError:
            format_enum = BankFormat.AUTO
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מנתח דף בנק...", total=None)
            result = service.import_statement(
                content=content,
                bank_format=format_enum,
                file_type=file_type,
                auto_categorize=True,
                create_transactions=not no_save
            )
        
        if not result['success']:
            console.print(f"❌ שגיאה: {result.get('error', 'Unknown error')}", style="bold red")
            return
        
        console.print(f"✅ נקלטו {result['parsed_transactions']} עסקאות!", style="bold green")
        
        if not no_save:
            console.print(f"   נשמרו: {result['created_transactions']}")
            console.print(f"   כפילויות: {result['duplicates_skipped']}")
        
        if 'analysis' in result:
            analysis = result['analysis']
            console.print(f"\n📊 [bold]ניתוח:[/bold]")
            console.print(f"   סה\"כ הכנסות: ₪{analysis['total_income']:,.0f}")
            console.print(f"   סה\"כ הוצאות: ₪{analysis['total_expenses']:,.0f}")
            console.print(f"   תזרים נקי: ₪{analysis['net_flow']:,.0f}")
            console.print(f"   תקופה: {analysis['date_range']['start']} עד {analysis['date_range']['end']}")
        
    finally:
        db.close()


@bank.command("patterns")
def bank_patterns():
    """Analyze spending patterns from imported bank transactions"""
    from .services.bank_statement_service import BankStatementService
    
    db = SessionLocal()
    try:
        service = BankStatementService(db, organization_id=1)
        result = service.get_spending_patterns()
        
        if not result.get('patterns'):
            console.print("❌ אין מספיק נתונים לניתוח", style="yellow")
            return
        
        table = Table(title="דפוסי הוצאות")
        table.add_column("קטגוריה", style="cyan")
        table.add_column("סה\"כ", justify="right")
        table.add_column("עסקאות", justify="center")
        table.add_column("אחוז", justify="right")
        table.add_column("ממוצע", justify="right")
        
        category_names = {
            'salary': 'משכורות',
            'utilities': 'חשבונות',
            'rent': 'שכירות',
            'groceries': 'מכולת',
            'transportation': 'תחבורה',
            'insurance': 'ביטוח',
            'bank_fees': 'עמלות',
            'credit_card': 'אשראי',
            'transfer': 'העברות',
            'loan': 'הלוואות',
            'investment': 'השקעות',
            'other': 'אחר'
        }
        
        for p in result['patterns']:
            cat_name = category_names.get(p['category'], p['category'])
            table.add_row(
                cat_name,
                f"₪{p['total']:,.0f}",
                str(p['count']),
                f"{p['percentage']:.1f}%",
                f"₪{p['average']:,.0f}"
            )
        
        console.print(table)
        console.print(f"\n💰 סה\"כ הוצאות: ₪{result['total_spending']:,.0f}")
        console.print(f"📊 מספר עסקאות: {result['transaction_count']}")
        
    finally:
        db.close()


@bank.command("recurring")
def bank_recurring():
    """Detect recurring transactions"""
    from .services.bank_statement_service import BankStatementService
    
    db = SessionLocal()
    try:
        service = BankStatementService(db, organization_id=1)
        result = service.detect_recurring_transactions()
        
        if not result:
            console.print("❌ לא נמצאו עסקאות חוזרות", style="yellow")
            return
        
        table = Table(title="עסקאות חוזרות")
        table.add_column("תיאור", style="cyan", max_width=40)
        table.add_column("סכום", justify="right")
        table.add_column("מופעים", justify="center")
        table.add_column("תדירות")
        table.add_column("מופע אחרון")
        
        freq_names = {
            'monthly': 'חודשי',
            'weekly': 'שבועי',
            'yearly': 'שנתי',
            'irregular': 'לא סדיר'
        }
        
        for tx in result[:20]:
            freq = freq_names.get(tx['frequency'], tx['frequency'])
            amount_style = "red" if tx['amount'] < 0 else "green"
            table.add_row(
                tx['description'][:40],
                f"[{amount_style}]₪{abs(tx['amount']):,.0f}[/{amount_style}]",
                str(tx['occurrences']),
                freq,
                tx['last_occurrence']
            )
        
        console.print(table)
        
    finally:
        db.close()


# ============= Financial Reports Commands =============

@cli.group()
def reports():
    """Financial reports generation commands"""
    pass


@reports.command("profit-loss")
@click.option("--start", "start_date", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--end", "end_date", default=None, help="End date (YYYY-MM-DD)")
@click.option("--export", "export_path", default=None, help="Export to Excel file path")
def reports_profit_loss(start_date: str, end_date: str, export_path: str):
    """Generate Profit & Loss report"""
    from .services.financial_reports_service import FinancialReportsService
    
    db = SessionLocal()
    try:
        service = FinancialReportsService(db, organization_id=1)
        
        # ברירות מחדל לתאריכים
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מייצר דוח רווח והפסד...", total=None)
            report = service.generate_profit_loss(
                start_date=datetime.strptime(start_date, '%Y-%m-%d'),
                end_date=datetime.strptime(end_date, '%Y-%m-%d')
            )
        
        # ייצוא ל-Excel
        if export_path:
            filepath = service.export_profit_loss_excel(report, export_path)
            console.print(f"✅ דוח יוצא ל: {filepath}", style="bold green")
            return
        
        # תצוגה בקונסול
        console.print(Panel(f"דוח רווח והפסד\n{start_date} - {end_date}", style="bold blue"))
        
        # הכנסות
        table = Table(title="הכנסות")
        table.add_column("קטגוריה", style="cyan")
        table.add_column("סכום", justify="right", style="green")
        table.add_column("אחוז", justify="right")
        
        for item in report.revenue:
            table.add_row(
                item.category_hebrew,
                f"₪{item.amount:,.0f}",
                f"{item.percentage:.1f}%"
            )
        table.add_row("[bold]סה״כ הכנסות[/bold]", f"[bold]₪{report.total_revenue:,.0f}[/bold]", "100%")
        console.print(table)
        
        # הוצאות תפעוליות
        table2 = Table(title="הוצאות תפעוליות")
        table2.add_column("קטגוריה", style="cyan")
        table2.add_column("סכום", justify="right", style="red")
        
        for item in report.operating_expenses:
            table2.add_row(item.category_hebrew, f"₪{abs(item.amount):,.0f}")
        console.print(table2)
        
        # סיכום
        summary_style = "green" if report.net_income >= 0 else "red"
        summary = f"""
[bold]רווח גולמי:[/bold] ₪{report.gross_profit:,.0f} ({report.gross_margin:.1f}%)
[bold]רווח תפעולי:[/bold] ₪{report.operating_income:,.0f} ({report.operating_margin:.1f}%)
[bold]רווח נקי:[/bold] [{summary_style}]₪{report.net_income:,.0f}[/{summary_style}] ({report.net_margin:.1f}%)
        """
        console.print(Panel(summary.strip(), title="סיכום", border_style=summary_style))
        
    finally:
        db.close()


@reports.command("balance-sheet")
@click.option("--date", "as_of_date", default=None, help="As of date (YYYY-MM-DD)")
@click.option("--export", "export_path", default=None, help="Export to Excel file path")
def reports_balance_sheet(as_of_date: str, export_path: str):
    """Generate Balance Sheet report"""
    from .services.financial_reports_service import FinancialReportsService
    
    db = SessionLocal()
    try:
        service = FinancialReportsService(db, organization_id=1)
        
        if not as_of_date:
            as_of_date = datetime.now().strftime('%Y-%m-%d')
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מייצר מאזן...", total=None)
            report = service.generate_balance_sheet(
                as_of_date=datetime.strptime(as_of_date, '%Y-%m-%d')
            )
        
        if export_path:
            filepath = service.export_balance_sheet_excel(report, export_path)
            console.print(f"✅ דוח יוצא ל: {filepath}", style="bold green")
            return
        
        console.print(Panel(f"מאזן ליום {as_of_date}", style="bold blue"))
        
        # נכסים
        table = Table(title="נכסים")
        table.add_column("פריט", style="cyan")
        table.add_column("סכום", justify="right", style="green")
        
        table.add_section()
        table.add_row("[bold]נכסים שוטפים[/bold]", "")
        for item in report.current_assets:
            table.add_row(f"  {item.name_hebrew}", f"₪{item.amount:,.0f}")
        table.add_row("[bold]סה״כ נכסים שוטפים[/bold]", f"[bold]₪{report.total_current_assets:,.0f}[/bold]")
        
        table.add_section()
        table.add_row("[bold]נכסים קבועים[/bold]", "")
        for item in report.fixed_assets:
            table.add_row(f"  {item.name_hebrew}", f"₪{item.amount:,.0f}")
        table.add_row("[bold]סה״כ נכסים קבועים[/bold]", f"[bold]₪{report.total_fixed_assets:,.0f}[/bold]")
        
        table.add_section()
        table.add_row("[bold cyan]סה״כ נכסים[/bold cyan]", f"[bold cyan]₪{report.total_assets:,.0f}[/bold cyan]")
        console.print(table)
        
        # התחייבויות והון
        table2 = Table(title="התחייבויות והון עצמי")
        table2.add_column("פריט", style="cyan")
        table2.add_column("סכום", justify="right")
        
        table2.add_section()
        table2.add_row("[bold]התחייבויות שוטפות[/bold]", "")
        for item in report.current_liabilities:
            table2.add_row(f"  {item.name_hebrew}", f"[red]₪{item.amount:,.0f}[/red]")
        table2.add_row("[bold]סה״כ התחייבויות שוטפות[/bold]", f"[bold red]₪{report.total_current_liabilities:,.0f}[/bold red]")
        
        table2.add_section()
        table2.add_row("[bold]הון עצמי[/bold]", "")
        for item in report.equity:
            table2.add_row(f"  {item.name_hebrew}", f"[green]₪{item.amount:,.0f}[/green]")
        table2.add_row("[bold]סה״כ הון עצמי[/bold]", f"[bold green]₪{report.total_equity:,.0f}[/bold green]")
        
        table2.add_section()
        table2.add_row("[bold magenta]סה״כ התחייבויות והון[/bold magenta]", 
                      f"[bold magenta]₪{report.total_liabilities + report.total_equity:,.0f}[/bold magenta]")
        console.print(table2)
        
        # בדיקת איזון
        if report.is_balanced:
            console.print("✅ המאזן מאוזן", style="bold green")
        else:
            console.print("❌ המאזן אינו מאוזן!", style="bold red")
        
    finally:
        db.close()


@reports.command("cash-projection")
@click.option("--months", default=12, help="Projection months")
@click.option("--export", "export_path", default=None, help="Export to Excel file path")
def reports_cash_projection(months: int, export_path: str):
    """Generate Cash Flow Projection (for bank)"""
    from .services.financial_reports_service import FinancialReportsService
    
    db = SessionLocal()
    try:
        service = FinancialReportsService(db, organization_id=1)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            progress.add_task(description="מייצר תחזית תזרים...", total=None)
            report = service.generate_cash_flow_projection(months=months)
        
        if export_path:
            filepath = service.export_cash_flow_projection_excel(report, export_path)
            console.print(f"✅ דוח יוצא ל: {filepath}", style="bold green")
            return
        
        console.print(Panel(f"תחזית תזרים מזומנים - {months} חודשים\n{report.company_name}", style="bold blue"))
        
        table = Table(title="תחזית חודשית")
        table.add_column("חודש", style="cyan")
        table.add_column("יתרת פתיחה", justify="right")
        table.add_column("כניסות", justify="right", style="green")
        table.add_column("יציאות", justify="right", style="red")
        table.add_column("נטו", justify="right")
        table.add_column("יתרת סגירה", justify="right")
        
        for proj in report.projections:
            net_style = "green" if proj.net_flow >= 0 else "red"
            closing_style = "green" if proj.closing_balance >= 0 else "red bold"
            table.add_row(
                proj.month,
                f"₪{proj.opening_balance:,.0f}",
                f"₪{proj.inflows:,.0f}",
                f"₪{proj.outflows:,.0f}",
                f"[{net_style}]₪{proj.net_flow:,.0f}[/{net_style}]",
                f"[{closing_style}]₪{proj.closing_balance:,.0f}[/{closing_style}]"
            )
        
        console.print(table)
        
        # סיכום
        summary = f"""
[bold]סה״כ כניסות צפויות:[/bold] ₪{report.total_projected_inflows:,.0f}
[bold]סה״כ יציאות צפויות:[/bold] ₪{report.total_projected_outflows:,.0f}
[bold]יתרה מינימלית:[/bold] ₪{report.minimum_balance:,.0f}
[bold]יתרת סגירה:[/bold] ₪{report.ending_balance:,.0f}
[bold]Runway:[/bold] {"∞ (תזרים חיובי)" if report.runway_months < 0 else f"{report.runway_months} חודשים"}
        """
        
        border_style = "green" if report.ending_balance >= 0 else "red"
        console.print(Panel(summary.strip(), title="סיכום", border_style=border_style))
        
        if report.minimum_balance < 0:
            console.print("⚠️  [yellow bold]אזהרה: צפוי גירעון בתזרים![/yellow bold]")
        
    finally:
        db.close()


@reports.command("export-all")
@click.option("--output-dir", default="./reports", help="Output directory")
def reports_export_all(output_dir: str):
    """Export all financial reports to Excel"""
    import os
    from .services.financial_reports_service import FinancialReportsService
    
    db = SessionLocal()
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        service = FinancialReportsService(db, organization_id=1)
        now = datetime.now()
        month_start = datetime(now.year, now.month, 1)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            # רווח והפסד
            task = progress.add_task(description="מייצר דוח רווח והפסד...", total=None)
            pl_report = service.generate_profit_loss(start_date=month_start, end_date=now)
            pl_path = service.export_profit_loss_excel(pl_report, os.path.join(output_dir, f"profit_loss_{now.strftime('%Y%m%d')}.xlsx"))
            progress.update(task, description=f"✅ {pl_path}")
            
            # מאזן
            task2 = progress.add_task(description="מייצר מאזן...", total=None)
            bs_report = service.generate_balance_sheet(as_of_date=now)
            bs_path = service.export_balance_sheet_excel(bs_report, os.path.join(output_dir, f"balance_sheet_{now.strftime('%Y%m%d')}.xlsx"))
            progress.update(task2, description=f"✅ {bs_path}")
            
            # תזרים חזוי
            task3 = progress.add_task(description="מייצר תחזית תזרים...", total=None)
            cf_report = service.generate_cash_flow_projection(months=12)
            cf_path = service.export_cash_flow_projection_excel(cf_report, os.path.join(output_dir, f"cash_flow_projection_{now.strftime('%Y%m%d')}.xlsx"))
            progress.update(task3, description=f"✅ {cf_path}")
        
        console.print(f"\n✅ כל הדוחות יוצאו ל: {output_dir}", style="bold green")
        
    finally:
        db.close()


if __name__ == "__main__":
    cli()
