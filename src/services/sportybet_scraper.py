import os
import json
from playwright.sync_api import sync_playwright
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def scrape_sportybet_code(booking_code: str):
    """
    Uses a headless Chromium browser to scrape the raw UI text from SportyBet
    and forwards it to Gemini Flash for precision JSON extraction.
    """
    print(f"🕵️‍♂️ Initiating Ghost Browser for code: {booking_code}...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # Navigate with a longer timeout and wait for idle
            page.goto("https://www.sportybet.com/ng/", timeout=60000, wait_until="networkidle")
            
            # Locate the "Booking Code" input field
            # Refined for strict mode: Targeting the unique data-op attribute for this field
            input_selector = 'input[data-op="desktop-booking-code-input"]'
            page.wait_for_selector(input_selector, timeout=20000)
            
            # 1. Focus and Fill (More robust than keyboard typing for reactive fields)
            print(f"Typing booking code: {booking_code}")
            input_el = page.locator(input_selector)
            input_el.click()
            input_el.fill(booking_code)
            
            # 2. Force events and verify value
            page.evaluate("""([sel, val]) => {
                const el = document.querySelector(sel);
                if (el) {
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.blur(); 
                }
            }""", [input_selector, booking_code])
            
            # VERIFICATION: Check if the value actually stuck
            current_val = input_el.input_value()
            print(f"DEBUG: Input value verification: '{current_val}'")
            
            page.wait_for_timeout(1000) 
            
            # 3. Click the "Load" button
            print("Clicking Load button...")
            load_button_selector = 'button[data-op="desktop-booking-code-load-button"], button:has-text("Load"), .m-booking-code-load, .m-btn-load'
            
            # Force enable if still disabled
            page.evaluate(f"""(sel) => {{
                const btn = document.querySelector(sel);
                if (btn) {{
                    btn.disabled = false;
                    btn.classList.remove('is-disabled');
                }}
            }}""", 'button[data-op="desktop-booking-code-load-button"], .m-booking-code-load, .m-btn-load')
            
            try:
                # Try clicking the button
                page.click(load_button_selector, timeout=5000)
            except Exception as e:
                print(f"⚠️ Button click failed ({e}), forcing click via JavaScript...")
                page.evaluate(f"document.querySelector('{load_button_selector}').click()")
            # 4. Wait for the betslip matches to render on the screen
            print("Waiting for network (extended 30s timeout)...")
            try:
                # Target the actual betslip match cards or container
                # Increased timeout to 30s for slower sessions
                page.wait_for_selector('.m-betslip-item, .m-bet-item, .m-betslip-content', timeout=30000)
            except Exception:
                print("Could not find betslip content. Capturing debug screenshot...")
                # Save screenshot to artifacts directory for visual diagnosis
                # Save screenshot to project root debug directory for environment safety
                debug_dir = os.path.join(os.getcwd(), "debug")
                if not os.path.exists(debug_dir):
                    os.makedirs(debug_dir)
                screenshot_path = os.path.join(debug_dir, f"sportybet_status_{booking_code}.png")
                page.screenshot(path=screenshot_path)
                print(f"📸 Debug screenshot saved: {screenshot_path}")
                
                # Check for error messages in the raw text
                raw_text_brief = page.locator('body').inner_text()[:1000]
                print(f"📄 Page Text Snippet: {raw_text_brief}")
                
                if "invalid" in raw_text_brief.lower() or "not found" in raw_text_brief.lower():
                    return {"booking_status": "failed", "error": f"SportyBet reported: {raw_text_brief[:100]}"}
            
            # 5. Extract specific betslip items
            print("Extracting betslip items...")
            betslip_raw_text = ""
            try:
                # Target the individual match cards in the betslip
                items = page.locator('.m-betslip-item, .m-bet-item').all_inner_texts()
                if items:
                    betslip_raw_text = "\n---\n".join(items)
                    print(f"✅ Found {len(items)} items in the actual betslip.")
            except Exception as e:
                print(f"⚠️ Failed to find items: {e}")

            if not betslip_raw_text:
                try:
                    # Fallback to the specific content container
                    betslip_raw_text = page.locator('.m-betslip-content').inner_text(timeout=5000)
                except Exception:
                    try:
                        # Fallback to the wrapper
                        betslip_raw_text = page.locator('.m-betslip-wrapper').inner_text(timeout=5000)
                    except Exception:
                        print("Could not find betslip containers. Grabbing right sidebar as fallback...")
                        betslip_raw_text = page.locator('.s-right').inner_text(timeout=5000)
            
            browser.close()
            
            if not betslip_raw_text or len(betslip_raw_text.strip()) < 10:
                return {"booking_status": "failed", "error": "No valid betslip content found."}
                
            return parse_betslip_with_ai(betslip_raw_text)
            
        except Exception as e:
            print(f"❌ Scraper failed: {e}")
            if 'browser' in locals():
                browser.close()
            return {"booking_status": "failed", "error": str(e)}

def parse_betslip_with_ai(raw_text: str):
    """
    Feeds the messy raw text into Gemini Flash to extract a clean JSON array of matches.
    """
    prompt = """
    You are a precision data extraction tool for OmniBet AI. 
    I will provide you with raw, messy scraped text from a sports betting betslip. 

    Your ONLY job is to identify the football matches AND the specific bet the user placed on that match.

    You MUST return your extraction strictly in JSON format with the following exact structure:
    {
      "booking_status": "success or failed",
      "total_matches_found": "integer",
      "matches": [
        {
          "home_team": "string",
          "away_team": "string",
          "match_date": "string (e.g. '2026-03-09' or 'Today')",
          "user_selected_bet": "string (e.g., 'Over 2.5 Goals', 'Home Win', 'GG/BTTS')"
        }
      ]
    }

    *** EXTRACTION RULES ***
    1. Look specifically for the list of matches that have a market/selection attached.
    2. Items in a betslip usually have a team pair (e.g., 'Wolves v Liverpool'), a market (e.g., 'Over 2'), and odds (e.g., '1.32').
    3. IGNORE everything under 'Popular Matches', 'Highlights', or 'Live Now'.
    4. Clean the team names (e.g., 'Wolves v Liverpool' -> home: 'Wolves', away: 'Liverpool').
    5. Ensure you extract the market correctly. If it says 'Over 2' for 'Over/Under', the selection is 'Over 2'.
    6. If the text is empty or clearly doesn't contain a betslip, set 'booking_status' to 'failed'.
    7. No conversational text. Output JSON only.
    """
    
    try:
        response = model.generate_content(prompt + "\n\nRAW TEXT:\n" + raw_text)
        
        # Clean the markdown formatting if present
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
            
        return json.loads(text.strip())
    except Exception as e:
        print(f"❌ Gemini parsing failed: {e}")
        return {"booking_status": "failed", "error": f"AI Parsing Error: {str(e)}"}
