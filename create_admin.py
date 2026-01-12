"""
Script to create initial super admin user
"""
import asyncio
from sqlalchemy.orm import Session
from rich.console import Console
from rich.prompt import Prompt

from cfo.database import SessionLocal, init_db
from cfo.models import User, UserRole
from cfo.auth import get_password_hash

console = Console()


def create_super_admin():
    """יצירת משתמש מנהל על ראשון"""
    console.print("\n[bold blue]🔐 CFO System - Super Admin Setup[/bold blue]\n")
    
    # Initialize database
    console.print("Initializing database...")
    init_db()
    console.print("✅ Database initialized\n")
    
    db: Session = SessionLocal()
    
    try:
        # Check if super admin already exists
        existing_admin = db.query(User).filter(
            User.role == UserRole.SUPER_ADMIN
        ).first()
        
        if existing_admin:
            console.print(f"[yellow]⚠️  Super admin already exists: {existing_admin.email}[/yellow]")
            overwrite = Prompt.ask("Do you want to create another super admin?", choices=["yes", "no"], default="no")
            if overwrite.lower() != "yes":
                console.print("[green]Setup cancelled[/green]")
                return
        
        # Get user input
        console.print("[cyan]Enter super admin details:[/cyan]\n")
        
        email = Prompt.ask("Email")
        full_name = Prompt.ask("Full Name")
        password = Prompt.ask("Password", password=True)
        confirm_password = Prompt.ask("Confirm Password", password=True)
        
        if password != confirm_password:
            console.print("[red]❌ Passwords don't match![/red]")
            return
        
        phone = Prompt.ask("Phone (optional)", default="")
        
        # Create super admin
        super_admin = User(
            email=email,
            password_hash=get_password_hash(password),
            full_name=full_name,
            phone=phone if phone else None,
            role=UserRole.SUPER_ADMIN,
            organization_id=None,  # Super admin not bound to any organization
            is_active=True
        )
        
        db.add(super_admin)
        db.commit()
        db.refresh(super_admin)
        
        console.print(f"\n[bold green]✅ Super admin created successfully![/bold green]")
        console.print(f"\n[cyan]Details:[/cyan]")
        console.print(f"  ID: {super_admin.id}")
        console.print(f"  Email: {super_admin.email}")
        console.print(f"  Name: {super_admin.full_name}")
        console.print(f"  Role: {super_admin.role.value}")
        console.print(f"\n[yellow]You can now login at: http://localhost:8000/api/docs[/yellow]\n")
        
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    create_super_admin()
