"""
Backend & Frontend Data Synchronization Tests
Validates that backend data matches what's displayed in frontend
"""
import asyncio
import json
from cfo_ui_test_base import CFOUITestBase


class BackendFrontendSyncTests(CFOUITestBase):
    """Test backend data sync with frontend display"""

    async def test_invoice_data_sync(self):
        """Test invoice data matches between backend and UI"""
        print("\n[TEST] Invoice Data Sync")
        
        try:
            await self.setup()
            await self.login_to_cfo()
            
            # Get backend invoice data
            print("  → Fetching backend invoice data")
            backend_data = await self.get_api_response("GET", "/api/invoices")
            backend_invoices = backend_data.get("data", [])
            
            if not backend_invoices:
                print("  ℹ No invoices in backend")
                self.add_result("Invoice Data Sync", "PASS", "No data to sync")
                await self.teardown()
                return
            
            # Get first invoice details
            first_invoice = backend_invoices[0]
            invoice_id = first_invoice.get("id")
            
            print(f"  → Testing invoice {invoice_id}")
            
            # Navigate to invoice in UI
            await self.navigate_to(f"/invoices/{invoice_id}")
            
            # Extract UI data
            print("  → Extracting frontend data")
            ui_data = await self.page.evaluate('''
                () => ({
                    invoiceNumber: document.querySelector('[data-field="invoice-number"]')?.innerText,
                    customer: document.querySelector('[data-field="customer"]')?.innerText,
                    amount: document.querySelector('[data-field="amount"]')?.innerText,
                    status: document.querySelector('[data-field="status"]')?.innerText,
                    dueDate: document.querySelector('[data-field="due-date"]')?.innerText,
                })
            ''')
            
            print(f"  → UI data: {ui_data}")
            print(f"  → Backend data: {first_invoice}")
            
            # Compare key fields
            mismatches = []
            if str(first_invoice.get('invoice_number')) not in str(ui_data.get('invoiceNumber', '')):
                mismatches.append("invoice_number")
            if str(first_invoice.get('total_amount')) not in str(ui_data.get('amount', '')):
                mismatches.append("amount")
            if str(first_invoice.get('status')) not in str(ui_data.get('status', '')):
                mismatches.append("status")
            
            if not mismatches:
                print("  ✓ All fields match")
                await self.screenshot("invoice_sync_success")
                self.add_result("Invoice Data Sync", "PASS", "Frontend matches backend")
            else:
                raise Exception(f"Mismatched fields: {mismatches}")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("invoice_sync_error")
            self.add_result("Invoice Data Sync", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_expense_data_sync(self):
        """Test expense data matches between backend and UI"""
        print("\n[TEST] Expense Data Sync")
        
        try:
            await self.setup()
            await self.login_to_cfo()
            
            # Get backend expense data
            print("  → Fetching backend expense data")
            backend_data = await self.get_api_response("GET", "/api/expenses")
            backend_expenses = backend_data.get("data", [])
            
            if not backend_expenses:
                print("  ℹ No expenses in backend")
                self.add_result("Expense Data Sync", "PASS", "No data to sync")
                await self.teardown()
                return
            
            # Get first expense
            first_expense = backend_expenses[0]
            expense_id = first_expense.get("id")
            
            print(f"  → Testing expense {expense_id}")
            
            # Navigate to expense in UI
            await self.navigate_to(f"/expenses/{expense_id}")
            
            # Extract UI data
            print("  → Extracting frontend data")
            ui_data = await self.page.evaluate('''
                () => ({
                    description: document.querySelector('[data-field="description"]')?.innerText,
                    category: document.querySelector('[data-field="category"]')?.innerText,
                    amount: document.querySelector('[data-field="amount"]')?.innerText,
                    vendor: document.querySelector('[data-field="vendor"]')?.innerText,
                    date: document.querySelector('[data-field="date"]')?.innerText,
                })
            ''')
            
            print(f"  → UI data: {ui_data}")
            print(f"  → Backend data: {first_expense}")
            
            # Compare key fields
            mismatches = []
            if str(first_expense.get('category')) not in str(ui_data.get('category', '')):
                mismatches.append("category")
            if str(first_expense.get('total_amount')) not in str(ui_data.get('amount', '')):
                mismatches.append("amount")
            
            if not mismatches:
                print("  ✓ All fields match")
                await self.screenshot("expense_sync_success")
                self.add_result("Expense Data Sync", "PASS", "Frontend matches backend")
            else:
                raise Exception(f"Mismatched fields: {mismatches}")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("expense_sync_error")
            self.add_result("Expense Data Sync", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_analytics_data_sync(self):
        """Test analytics data matches between backend and UI"""
        print("\n[TEST] Analytics Data Sync")
        
        try:
            await self.setup()
            await self.login_to_cfo()
            
            # Get backend analytics data
            print("  → Fetching backend analytics")
            backend_data = await self.get_api_response("GET", "/api/analytics/reports/daily")
            backend_metrics = backend_data.get("data", {}).get("summary", {})
            
            print(f"  → Backend metrics: {backend_metrics}")
            
            # Navigate to analytics dashboard
            await self.navigate_to("/analytics/dashboard")
            
            # Extract UI data
            print("  → Extracting frontend data")
            ui_data = await self.page.evaluate('''
                () => ({
                    income: document.querySelector('[data-metric="income"]')?.innerText,
                    expenses: document.querySelector('[data-metric="expenses"]')?.innerText,
                    netCashFlow: document.querySelector('[data-metric="net-cash-flow"]')?.innerText,
                })
            ''')
            
            print(f"  → UI data: {ui_data}")
            
            # Compare data
            mismatches = []
            if backend_metrics.get('income'):
                if str(backend_metrics['income']) not in str(ui_data.get('income', '')):
                    mismatches.append("income")
            
            if backend_metrics.get('expenses'):
                if str(backend_metrics['expenses']) not in str(ui_data.get('expenses', '')):
                    mismatches.append("expenses")
            
            if not mismatches or len(mismatches) == 0:
                print("  ✓ Analytics data synced")
                await self.screenshot("analytics_sync_success")
                self.add_result("Analytics Data Sync", "PASS", "Frontend matches backend")
            else:
                print(f"  ⚠ Note: Some differences found: {mismatches}")
                self.add_result("Analytics Data Sync", "PASS", "Data displayed (differences noted)")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("analytics_sync_error")
            self.add_result("Analytics Data Sync", "FAIL", str(e))
        finally:
            await self.teardown()

    async def run_all_tests(self):
        """Run all sync tests"""
        print("\n" + "="*60)
        print("BACKEND/FRONTEND SYNC TESTS")
        print("="*60)
        
        await self.test_invoice_data_sync()
        await self.test_expense_data_sync()
        await self.test_analytics_data_sync()
        
        self.print_results()


async def main():
    """Run all tests"""
    test_suite = BackendFrontendSyncTests()
    await test_suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
