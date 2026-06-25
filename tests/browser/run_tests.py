#!/usr/bin/env python3
"""
Complete Test Runner for CFO System
Runs all SUMIT integration tests, CFO UI tests, and data validation tests
"""
import os
import sys
import asyncio
from pathlib import Path

# Add test directories to path
sys.path.insert(0, str(Path(__file__).parent / "sumit_integration"))
sys.path.insert(0, str(Path(__file__).parent / "cfo_ui_tests"))
sys.path.insert(0, str(Path(__file__).parent / "data_validation"))

# Import all test suites
from sumit_connection_tests import SUMITConnectionTests
from dashboard_ui_tests import DashboardUITests
from backend_frontend_sync import BackendFrontendSyncTests


class CompletTestRunner:
    """Run all test suites"""
    
    def __init__(self):
        self.all_results = []
        self.start_time = None
        # FIX #6: Track test suites for cleanup
        self.test_suites = []
        
    async def run_all(self):
        """Run all test suites"""
        print("\n" + "="*70)
        print("CFO SYSTEM - COMPLETE INTEGRATION TEST SUITE")
        print("="*70)
        
        try:
            # Run SUMIT tests
            print("\n[RUNNING] SUMIT Integration Tests")
            print("-"*70)
            sumit_tests = SUMITConnectionTests()
            self.test_suites.append(sumit_tests)
            await sumit_tests.run_all_tests()
            self.all_results.extend(sumit_tests.test_results)
            
            # Run CFO UI tests
            print("\n[RUNNING] CFO UI Tests")
            print("-"*70)
            ui_tests = DashboardUITests()
            self.test_suites.append(ui_tests)
            await ui_tests.run_all_tests()
            self.all_results.extend(ui_tests.test_results)
            
            # Run data sync tests
            print("\n[RUNNING] Data Synchronization Tests")
            print("-"*70)
            sync_tests = BackendFrontendSyncTests()
            self.test_suites.append(sync_tests)
            await sync_tests.run_all_tests()
            self.all_results.extend(sync_tests.test_results)
            
            # Print final summary
            self.print_final_summary()
        finally:
            # FIX #6: Cleanup playwright resources on exit (success or exception)
            await self._cleanup_all()
    
    async def _cleanup_all(self):
        """Cleanup all test resources"""
        for suite in self.test_suites:
            try:
                if hasattr(suite, 'teardown'):
                    await suite.teardown()
            except Exception as e:
                print(f"  ⚠ Cleanup error for {suite.__class__.__name__}: {e}")
    
    def print_final_summary(self):
        """Print final test summary"""
        print("\n" + "="*70)
        print("FINAL TEST SUMMARY")
        print("="*70)
        
        passed = sum(1 for r in self.all_results if r["status"] == "PASS")
        failed = sum(1 for r in self.all_results if r["status"] == "FAIL")
        total = len(self.all_results)
        
        print(f"\nTotal Tests: {total}")
        print(f"Passed: {passed} ✓")
        print(f"Failed: {failed} ✗")
        print(f"Pass Rate: {(passed/total*100):.1f}%")
        
        if failed > 0:
            print("\nFailed Tests:")
            for result in self.all_results:
                if result["status"] == "FAIL":
                    print(f"  ✗ {result['test']}")
                    if result['message']:
                        print(f"    → {result['message']}")
        
        print("\n" + "="*70)
        
        return failed == 0


async def main():
    """Main entry point"""
    runner = CompletTestRunner()
    success = await runner.run_all()
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
