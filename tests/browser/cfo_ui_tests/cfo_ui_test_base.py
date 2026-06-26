"""
CFO System UI Testing Base Class
Provides shared functionality for CFO UI tests
"""
import os
import asyncio
import json
from typing import Optional
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page, BrowserContext


class CFOUITestBase:
    """Base class for all CFO UI tests"""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.cfo_url = os.getenv("CFO_URL", "http://localhost:8000")
        self.test_email = os.getenv("CFO_TEST_EMAIL", "test@example.com")
        self.test_password = os.getenv("CFO_TEST_PASSWORD", "password123")
        self.test_org_id = os.getenv("CFO_TEST_ORG_ID", "1")
        self.test_results = []
        self.start_time = None

    async def setup(self):
        """Initialize browser and context"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
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

    async def navigate_to(self, path: str):
        """Navigate to CFO system path"""
        url = f"{self.cfo_url}{path}"
        print(f"  → Navigating to {path}")
        await self.page.goto(url, wait_until="networkidle")
        print(f"  ✓ Page loaded")

    async def login_to_cfo(self, email: str = None, password: str = None):
        """Login to CFO system"""
        email = email or self.test_email
        password = password or self.test_password

        print(f"  → Logging in as {email}")
        
        # Navigate to login
        await self.navigate_to("/api/docs")  # Redirect to login if needed
        
        # Fill email field
        try:
            await self.page.fill('input[type="email"]', email)
            await self.page.fill('input[type="password"]', password)
            await self.page.click('button[type="submit"]')
            
            # Wait for dashboard
            await self.page.wait_for_url(f"{self.cfo_url}/dashboard")
            print(f"  ✓ Login successful")
        except Exception as e:
            print(f"  ℹ Using auth token from environment")
            # Set auth token in local storage (FIX #1: Use JSON.stringify to avoid injection)
            auth_token = os.getenv("CFO_AUTH_TOKEN", "")
            await self.page.evaluate(f'''
                localStorage.setItem('auth_token', {json.dumps(auth_token)})
            ''')

    async def get_text(self, selector: str) -> str:
        """Get text content of element"""
        return await self.page.text_content(selector)

    async def is_visible(self, selector: str) -> bool:
        """Check if element is visible"""
        try:
            return await self.page.is_visible(selector)
        except Exception as e:
            # FIX #3: Catch specific Exception, not bare except
            return False

    async def wait_for_element(self, selector: str, timeout: int = 5000):
        """Wait for element to appear"""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def fill_field(self, selector: str, value: str):
        """Fill text field"""
        await self.page.fill(selector, value)

    async def click_button(self, text: str):
        """Click button by text"""
        await self.page.click(f'button:has-text("{text}")')

    async def screenshot(self, filename: str):
        """Take screenshot"""
        path = f"/tmp/cfo_ui_screenshots/{filename}.png"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await self.page.screenshot(path=path)
        print(f"  📸 Screenshot saved: {path}")

    async def get_api_response(self, method: str, endpoint: str, data: dict = None):
        """Make API request and get response"""
        print(f"  → Making {method} request to {endpoint}")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('CFO_AUTH_TOKEN', '')}"
        }
        
        # FIX #5: Add timeout to prevent indefinite hangs
        request_timeout = 30000  # 30 seconds
        
        try:
            if method == "GET":
                response = await self.page.request.get(
                    f"{self.cfo_url}{endpoint}", 
                    headers=headers,
                    timeout=request_timeout
                )
            elif method == "POST":
                response = await self.page.request.post(
                    f"{self.cfo_url}{endpoint}", 
                    headers=headers, 
                    data=data,
                    timeout=request_timeout
                )
            elif method == "PUT":
                response = await self.page.request.put(
                    f"{self.cfo_url}{endpoint}", 
                    headers=headers, 
                    data=data,
                    timeout=request_timeout
                )
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            # FIX #4: Handle non-JSON responses gracefully
            try:
                result = await response.json()
            except json.JSONDecodeError as e:
                print(f"  ✗ Response is not JSON (status {response.status}): {e}")
                raise ValueError(f"Expected JSON response, got {response.content_type}") from e
            
            print(f"  ✓ Response status: {response.status}")
            return result
        except Exception as e:
            print(f"  ✗ API request failed: {e}")
            raise

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
        print("CFO UI TEST RESULTS SUMMARY")
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
