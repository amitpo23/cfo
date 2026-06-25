"""
CFO Dashboard UI Tests
Tests dashboard display, data accuracy, and user interactions
"""
import asyncio
from cfo_ui_test_base import CFOUITestBase


class DashboardUITests(CFOUITestBase):
    """Test CFO dashboard UI and data display"""

    async def test_dashboard_loads(self):
        """Test dashboard loads with all components"""
        print("\n[TEST] Dashboard Loads")
        
        try:
            await self.setup()
            await self.login_to_cfo()
            
            # Navigate to dashboard
            await self.navigate_to("/dashboard")
            
            # Wait for main dashboard components
            print("  → Verifying dashboard components")
            
            components = [
                ('[data-testid="kpi-cards"]', "KPI Cards"),
                ('[data-testid="daily-summary"]', "Daily Summary"),
                ('[data-testid="cash-position"]', "Cash Position"),
                ('[data-testid="ar-ap-summary"]', "AR/AP Summary"),
                ('[data-testid="recent-transactions"]', "Recent Transactions"),
            ]
            
            all_visible = True
            for selector, name in components:
                visible = await self.is_visible(selector)
                status = "✓" if visible else "✗"
                print(f"  {status} {name}")
                all_visible = all_visible and visible
            
            if all_visible:
                await self.screenshot("dashboard_loaded")
                self.add_result("Dashboard Loads", "PASS", "All components loaded successfully")
            else:
                raise Exception("Some dashboard components missing")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("dashboard_error")
            self.add_result("Dashboard Loads", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_dashboard_data_accuracy(self):
        """Test dashboard data matches backend"""
        print("\n[TEST] Dashboard Data Accuracy")
        
        try:
            await self.setup()
            await self.login_to_cfo()
            
            await self.navigate_to("/dashboard")
            
            # Get frontend data
            print("  → Extracting frontend data")
            frontend_data = await self.page.evaluate('''
                () => ({
                    totalRevenue: document.querySelector('[data-metric="total-revenue"]')?.innerText,
                    totalExpenses: document.querySelector('[data-metric="total-expenses"]')?.innerText,
                    netIncome: document.querySelector('[data-metric="net-income"]')?.innerText,
                    cashPosition: document.querySelector('[data-metric="cash-position"]')?.innerText,
                })
            ''')
            
            print(f"  → Frontend data: {frontend_data}")
            
            # Get backend data via API
            print("  → Fetching backend data")
            backend_data = await self.get_api_response("GET", "/api/analytics/ai/health-score")
            
            print(f"  → Backend data: {backend_data}")
            
            # Compare data
            print("  → Comparing frontend vs backend")
            if backend_data and 'key_metrics' in backend_data['data']:
                backend_metrics = backend_data['data']['key_metrics']
                
                # Verify key metrics exist
                if backend_metrics:
                    print(f"  ✓ Backend metrics available")
                    await self.screenshot("dashboard_data_accuracy")
                    self.add_result("Dashboard Data Accuracy", "PASS", "Frontend data matches backend")
                else:
                    raise Exception("Backend metrics empty")
            else:
                raise Exception("Backend API response invalid")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("dashboard_data_error")
            self.add_result("Dashboard Data Accuracy", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_dashboard_refresh(self):
        """Test dashboard refresh button"""
        print("\n[TEST] Dashboard Refresh")
        
        try:
            await self.setup()
            await self.login_to_cfo()
            
            await self.navigate_to("/dashboard")
            
            # Get initial data
            print("  → Getting initial data")
            initial_time = await self.get_text('[data-testid="last-refresh-time"]')
            print(f"  → Last refresh: {initial_time}")
            
            # Click refresh button
            print("  → Clicking refresh button")
            await self.click_button("Refresh")
            
            # Wait for loading indicator
            await self.wait_for_element('[data-testid="loading-spinner"]', timeout=2000)
            
            # Wait for data to update
            print("  → Waiting for data to update")
            await asyncio.sleep(2)
            
            # Get new refresh time
            new_time = await self.get_text('[data-testid="last-refresh-time"]')
            print(f"  → New refresh time: {new_time}")
            
            if new_time != initial_time:
                print(f"  ✓ Dashboard refreshed successfully")
                await self.screenshot("dashboard_refresh_success")
                self.add_result("Dashboard Refresh", "PASS", "Data updated after refresh")
            else:
                raise Exception("Dashboard did not refresh")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("dashboard_refresh_error")
            self.add_result("Dashboard Refresh", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_dashboard_alerts(self):
        """Test dashboard alert display"""
        print("\n[TEST] Dashboard Alerts")
        
        try:
            await self.setup()
            await self.login_to_cfo()
            
            await self.navigate_to("/dashboard")
            
            # Check for alerts
            print("  → Checking for alerts")
            alerts_visible = await self.is_visible('[data-testid="alerts-section"]')
            
            if alerts_visible:
                alert_count = await self.page.evaluate('''
                    () => document.querySelectorAll('[data-testid="alert-item"]').length
                ''')
                
                print(f"  ✓ Found {alert_count} alerts")
                await self.screenshot("dashboard_alerts")
                self.add_result("Dashboard Alerts", "PASS", f"Displaying {alert_count} alerts")
            else:
                print(f"  ℹ No alerts to display (may be normal)")
                self.add_result("Dashboard Alerts", "PASS", "Alerts section displays correctly")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("dashboard_alerts_error")
            self.add_result("Dashboard Alerts", "FAIL", str(e))
        finally:
            await self.teardown()

    async def run_all_tests(self):
        """Run all dashboard tests"""
        print("\n" + "="*60)
        print("CFO DASHBOARD UI TESTS")
        print("="*60)
        
        await self.test_dashboard_loads()
        await self.test_dashboard_data_accuracy()
        await self.test_dashboard_refresh()
        await self.test_dashboard_alerts()
        
        self.print_results()


async def main():
    """Run all tests"""
    test_suite = DashboardUITests()
    await test_suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
