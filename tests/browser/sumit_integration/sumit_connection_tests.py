"""
SUMIT Connection Tests
Tests the client business account connection workflow
"""
import asyncio
from sumit_test_base import SUMITTestBase


class SUMITConnectionTests(SUMITTestBase):
    """Test SUMIT client business account connection"""

    async def test_connect_existing_authorized_client(self):
        """
        Test Scenario A: Client already authorized
        Expected: Connection executes immediately
        """
        print("\n[TEST] Connect Existing Authorized Client")
        
        try:
            await self.setup()
            await self.login_to_sumit()
            
            # Navigate to client file
            print("  → Opening client file list")
            await self.navigate_to(f"{self.sumit_url}/files")
            await self.wait_for_element('[data-testid="file-list"]')
            
            # Find test client file
            print("  → Finding test client file")
            await self.page.click('text=Test Client File')
            await self.wait_for_element('[data-testid="file-detail"]')
            
            # Click "Connect Client Business" button
            print("  → Clicking 'Connect Client Business' button")
            await self.click_button("Connect Client Business")
            
            # Should see existing client option
            await self.wait_for_element('[data-testid="existing-client-option"]')
            existing_client_visible = await self.is_visible('[data-testid="existing-client-option"]')
            
            if existing_client_visible:
                print("  → Found existing client option")
                await self.page.click('[data-testid="existing-client-option"]')
                
                # Select the authorized client
                await self.page.click('text=Authorized Client')
                
                # Click confirm
                await self.click_button("Confirm Connection")
                
                # Wait for success message
                await self.wait_for_element('[data-testid="connection-success"]')
                success_text = await self.get_text('[data-testid="connection-success"]')
                
                print(f"  ✓ Connection successful: {success_text}")
                await self.screenshot("connection_success_scenario_a")
                self.add_result("Connect Existing Authorized Client", "PASS", "Connection completed immediately")
            else:
                raise Exception("Existing client option not found")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("connection_error_scenario_a")
            self.add_result("Connect Existing Authorized Client", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_connect_pending_authorization_client(self):
        """
        Test Scenario B: Client authorization pending
        Expected: System sends email, connection completes upon approval
        """
        print("\n[TEST] Connect Pending Authorization Client")
        
        try:
            await self.setup()
            await self.login_to_sumit()
            
            # Navigate to client file
            await self.navigate_to(f"{self.sumit_url}/files")
            await self.wait_for_element('[data-testid="file-list"]')
            
            # Find test client file (pending auth)
            print("  → Finding pending auth client file")
            await self.page.click('text=Pending Auth Client')
            await self.wait_for_element('[data-testid="file-detail"]')
            
            # Click "Connect Client Business" button
            print("  → Clicking 'Connect Client Business' button")
            await self.click_button("Connect Client Business")
            
            # Should see pending auth option
            await self.wait_for_element('[data-testid="pending-auth-option"]')
            
            print("  → Found pending auth option")
            await self.page.click('[data-testid="pending-auth-option"]')
            
            # System should show "Sending authorization email"
            await self.wait_for_element('[data-testid="auth-email-sending"]')
            sending_text = await self.get_text('[data-testid="auth-email-sending"]')
            print(f"  → Email status: {sending_text}")
            
            # Verify confirmation message
            await self.wait_for_element('[data-testid="auth-email-sent"]')
            sent_text = await self.get_text('[data-testid="auth-email-sent"]')
            print(f"  ✓ Authorization email sent: {sent_text}")
            
            await self.screenshot("connection_pending_auth_scenario_b")
            self.add_result("Connect Pending Authorization Client", "PASS", "Authorization email sent successfully")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("connection_error_scenario_b")
            self.add_result("Connect Pending Authorization Client", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_connect_new_client_account(self):
        """
        Test Scenario C: No existing account
        Expected: System creates account and sends invitation
        """
        print("\n[TEST] Connect New Client Account")
        
        try:
            await self.setup()
            await self.login_to_sumit()
            
            # Navigate to client file
            await self.navigate_to(f"{self.sumit_url}/files")
            await self.wait_for_element('[data-testid="file-list"]')
            
            # Find test client file (new client)
            print("  → Finding new client file")
            await self.page.click('text=New Client File')
            await self.wait_for_element('[data-testid="file-detail"]')
            
            # Click "Connect Client Business" button
            print("  → Clicking 'Connect Client Business' button")
            await self.click_button("Connect Client Business")
            
            # Should see new account option
            await self.wait_for_element('[data-testid="new-account-option"]')
            
            print("  → Found new account option")
            await self.page.click('[data-testid="new-account-option"]')
            
            # System should create account automatically
            await self.wait_for_element('[data-testid="account-created"]')
            created_text = await self.get_text('[data-testid="account-created"]')
            print(f"  → Account created: {created_text}")
            
            # Verify invitation email sent
            await self.wait_for_element('[data-testid="invitation-email-sent"]')
            invitation_text = await self.get_text('[data-testid="invitation-email-sent"]')
            print(f"  ✓ Invitation email sent: {invitation_text}")
            
            # Verify connection established
            await self.wait_for_element('[data-testid="connection-established"]')
            connection_text = await self.get_text('[data-testid="connection-established"]')
            print(f"  ✓ Connection established: {connection_text}")
            
            await self.screenshot("connection_new_account_scenario_c")
            self.add_result("Connect New Client Account", "PASS", "Account created and invitation sent")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("connection_error_scenario_c")
            self.add_result("Connect New Client Account", "FAIL", str(e))
        finally:
            await self.teardown()

    async def test_disconnect_client_business(self):
        """
        Test disconnection workflow
        Expected: File-to-business link removed, permissions preserved
        """
        print("\n[TEST] Disconnect Client Business")
        
        try:
            await self.setup()
            await self.login_to_sumit()
            
            # Navigate to connected client file
            await self.navigate_to(f"{self.sumit_url}/files")
            await self.wait_for_element('[data-testid="file-list"]')
            
            print("  → Finding connected client file")
            await self.page.click('text=Connected Client')
            await self.wait_for_element('[data-testid="file-detail"]')
            
            # Verify connection status
            connection_status = await self.get_text('[data-testid="connection-status"]')
            print(f"  → Current connection status: {connection_status}")
            
            # Navigate to More > Additional Links > Advanced Actions
            print("  → Opening More menu")
            await self.click_button("More")
            
            print("  → Clicking Additional Links")
            await self.page.click('text=Additional Links')
            
            print("  → Clicking Advanced Actions")
            await self.page.click('text=Advanced Actions')
            
            # Click Disconnect button
            print("  → Clicking Disconnect Client Business")
            await self.click_button("Disconnect Client Business from Your Firm")
            
            # Confirm disconnection
            await self.wait_for_element('[data-testid="disconnect-confirm"]')
            await self.click_button("Confirm Disconnect")
            
            # Verify disconnection
            await self.wait_for_element('[data-testid="disconnection-success"]')
            success_text = await self.get_text('[data-testid="disconnection-success"]')
            print(f"  ✓ Disconnection successful: {success_text}")
            
            # Verify permissions still exist
            print("  → Verifying user permissions preserved")
            await self.navigate_to(f"{self.sumit_url}/files/{self.current_file_id}/permissions")
            permissions_exist = await self.is_visible('[data-testid="permissions-list"]')
            
            if permissions_exist:
                print(f"  ✓ User permissions preserved")
                self.add_result("Disconnect Client Business", "PASS", "Disconnection successful, permissions preserved")
            else:
                raise Exception("User permissions were removed")
            
            await self.screenshot("disconnection_success")
                
        except Exception as e:
            print(f"  ✗ Test failed: {str(e)}")
            await self.screenshot("disconnection_error")
            self.add_result("Disconnect Client Business", "FAIL", str(e))
        finally:
            await self.teardown()

    async def run_all_tests(self):
        """Run all connection tests"""
        print("\n" + "="*60)
        print("SUMIT CONNECTION INTEGRATION TESTS")
        print("="*60)
        
        await self.test_connect_existing_authorized_client()
        await self.test_connect_pending_authorization_client()
        await self.test_connect_new_client_account()
        await self.test_disconnect_client_business()
        
        self.print_results()


async def main():
    """Run all tests"""
    test_suite = SUMITConnectionTests()
    await test_suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
