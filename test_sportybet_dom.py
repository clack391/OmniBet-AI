import os
from playwright.sync_api import sync_playwright

def test_scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Navigating to Sportybet...")
        page.goto("https://www.sportybet.com/ng/", wait_until="domcontentloaded", timeout=60000)
        
        # Take a screenshot right away
        print("Taking initial screenshot...")
        page.screenshot(path="sportybet_initial.png")
        
        try:
            print("Filling code...")
            page.fill('input[placeholder="Booking Code"]', "T1RNTQ", timeout=5000)
            print("Clicking Load...")
            page.click('button:has-text("Load")', timeout=5000)
            print("Waiting 3s for network...")
            page.wait_for_timeout(3000)
            
            # Save screenshot to investigate DOM visually
            page.screenshot(path="sportybet_loaded.png")
            print("Screenshot saved to sportybet_loaded.png")
            
            # Print page content snippet
            html = page.content()
            with open("sportybet_dom.html", "w") as f:
                f.write(html)
            
        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="sportybet_error.png")
            
        browser.close()

if __name__ == "__main__":
    test_scrape()
