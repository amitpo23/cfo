"""
Main CLI entry point for CFO system
"""
import click
import asyncio
from rich.console import Console
from rich.table import Table

from .config import settings
from .database import init_db
from .integrations.sumit_integration import SumitIntegration

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
            company_id=settings.sumit_company_id
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


if __name__ == "__main__":
    cli()
