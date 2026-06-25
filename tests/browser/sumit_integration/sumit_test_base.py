"""
SUMIT Integration Testing Base Class
Provides shared functionality for all SUMIT browser tests
"""
import os
import asyncio
from typing import Optional
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page, BrowserContext


class SUMITTestBase:
    """Base class for all SUMIT integration tests"""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.sumit_url = os.getenv("SUMIT_URL", "https://secure.sumit.co.il")
        self.sumit_email = os.getenv("SUMIT_TEST_EMAIL", "test@example.com")
        self.sumit_password = os.getenv("SUMIT_TEST_PASSWORD", "")
        self.test_results = []
        self.start_time = None

    async def setup(self):
        """Initialize browser and context"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            record_video_dir="/tmp/sumit_tests_videos" if os.getenv("RECORD_VIDEO") else None
        )
        self.page = await self.context.new_page()
        self.start_time = datetime.now()
        print(f"✓ Browser setup complete at {self.start_time}")

    async def teardown(self):
        """Close browser and context"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        print(f"✓ Browser teardown complete")

    async def navigate_to(self, url: str):
        """Navigate to URL and wait for load"""
        print(f"  → Navigating to {url}")
        await self.page.goto(url, wait_until="networkidle")
        print(f"  ✓ Page loaded")

    async def login_to_sumit(self, email: str = None, password: str = None):
        """Login to SUMIT with credentials"""
        email = email or self.sumit_email
        password = password or self.sumit_password

        if not password:
            raise ValueError("SUMIT password not set in environment")

        print(f"  → Logging in as {email}")
        
        # Navigate to login
        await self.navigate_to(f"{self.sumit_url}/login")
        
        # Fill email field
        await self.page.fill('input[type="email"]', email)
        
        # Fill password field
        await self.page.fill('input[type="password"]', password)
        
        # Click login button
        await self.page.click('button[type="submit"]')
        
        # Wait for dashboard to load
        await self.page.wait_for_url(f"{self.sumit_url}/dashboard")
        print(f"  ✓ Login successful")

    async def get_text(self, selector: str) -> str:
        """Get text content of element"""
        return await self.page.text_content(selector)

    async def is_visible(self, selector: str) -> bool:
        """Check if element is visible"""
        try:
            return await self.page.is_visible(selector)
        except:
            return False

    async def wait_for_element(self, selector: str, timeout: int = 5000):
        """Wait for element to appear"""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def click_button(self, text: str):
        """Click button by text"""
        await self.page.click(f'button:has-text("{text}")')

    async def screenshot(self, filename: str):
        """Take screenshot"""
        path = f"/tmp/sumit_screenshots/{filename}.png"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await self.page.screenshot(path=path)
        print(f"  📸 Screenshot saved: {path}")

    def add_result(self, test_name: str, status: str, message: str = ""):
        """Add test result"""
        self.test_results.append({
            "test": test_name,
            "status": status,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })

    def print_results(self):
        """Print all test results"""
        print("\n" + "="*60)
        print("TEST RESULTS SUMMARY")
        print("="*60)
        
        passed = sum(1 for r in self.test_results if r["status"] == "PASS")
        failed = sum(1 for r in self.test_results if r["status"] == "FAIL")
        
        for result in self.test_results:
            symbol = "✓" if result["status"] == "PASS" else "✗"
            print(f"{symbol} {result['test']}: {result['status']}")
            if result["message"]:
                print(f"  → {result['message']}")
        
        print("\n" + "-"*60)
        print(f"Total: {len(self.test_results)} | Passed: {passed} | Failed: {failed}")
        print("="*60 + "\n")

    async def run_with_retry(self, func, max_retries: int = 3):
        """Run function with retry logic"""
        for attempt in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                print(f"  ⚠ Attempt {attempt + 1} failed, retrying...")
                await asyncio.sleep(2 ** attempt)
