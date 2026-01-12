"""
Example usage of SUMIT Integration
"""
import asyncio
from decimal import Decimal
from datetime import date

from src.cfo.integrations.sumit_integration import SumitIntegration
from src.cfo.integrations.sumit_models import (
    CustomerRequest,
    DocumentRequest,
    DocumentItem,
    ChargeRequest,
    SMSRequest,
)


async def main():
    """Example usage of SUMIT API integration"""
    
    # Initialize integration (use your API key)
    api_key = "your_sumit_api_key_here"
    
    async with SumitIntegration(api_key=api_key) as sumit:
        print("🔌 Testing SUMIT API Connection...")
        
        # Test connection
        is_connected = await sumit.test_connection()
        print(f"✅ Connection status: {'Connected' if is_connected else 'Failed'}")
        
        if not is_connected:
            print("❌ Cannot connect to SUMIT API. Check your API key.")
            return
        
        # Example 1: Create a customer
        print("\n👤 Creating a customer...")
        try:
            customer = await sumit.create_customer(
                CustomerRequest(
                    name="Test Customer Ltd.",
                    email="test@example.com",
                    phone="+972501234567",
                    tax_id="123456789"
                )
            )
            print(f"✅ Created customer: {customer.customer_id}")
            customer_id = customer.customer_id
        except Exception as e:
            print(f"❌ Error creating customer: {e}")
            return
        
        # Example 2: Create an invoice
        print("\n📄 Creating an invoice...")
        try:
            invoice = await sumit.create_document(
                DocumentRequest(
                    customer_id=customer_id,
                    document_type="invoice",
                    items=[
                        DocumentItem(
                            description="Consulting Services - January",
                            quantity=Decimal("10"),
                            price=Decimal("500")
                        ),
                        DocumentItem(
                            description="Software License",
                            quantity=Decimal("1"),
                            price=Decimal("1000")
                        )
                    ],
                    issue_date=date.today()
                )
            )
            print(f"✅ Created invoice: {invoice.document_number}")
            print(f"   Total: {invoice.currency} {invoice.total_amount}")
        except Exception as e:
            print(f"❌ Error creating invoice: {e}")
        
        # Example 3: List income items
        print("\n📦 Listing income items...")
        try:
            items = await sumit.list_income_items()
            print(f"✅ Found {len(items)} income items")
            for item in items[:3]:  # Show first 3
                print(f"   - {item.name}: {item.currency} {item.price}")
        except Exception as e:
            print(f"❌ Error listing items: {e}")
        
        # Example 4: Get account balance
        print("\n💰 Getting account balance...")
        try:
            balance = await sumit.get_balance()
            print(f"✅ Balance information retrieved")
            print(f"   Data: {balance}")
        except Exception as e:
            print(f"❌ Error getting balance: {e}")
        
        # Example 5: Send SMS (optional - requires SMS credits)
        print("\n📱 Sending SMS (commented out by default)...")
        # Uncomment to test SMS:
        # try:
        #     sms = await sumit.send_sms(
        #         SMSRequest(
        #             phone_number="+972501234567",
        #             message="Test message from CFO system"
        #         )
        #     )
        #     print(f"✅ SMS sent: {sms.message_id}")
        # except Exception as e:
        #     print(f"❌ Error sending SMS: {e}")
        
        # Example 6: List CRM folders
        print("\n📁 Listing CRM folders...")
        try:
            folders = await sumit.list_folders()
            print(f"✅ Found {len(folders)} CRM folders")
            for folder in folders[:3]:  # Show first 3
                print(f"   - {folder.folder_name} (ID: {folder.folder_id})")
        except Exception as e:
            print(f"❌ Error listing folders: {e}")
        
        print("\n✨ Examples completed!")


if __name__ == "__main__":
    print("=" * 60)
    print("SUMIT API Integration - Example Usage")
    print("=" * 60)
    print()
    
    # Run async main
    asyncio.run(main())
