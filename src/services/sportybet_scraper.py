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
            # Navigate to the Nigerian platform
            page.goto("https://www.sportybet.com/ng/")
            
            # Locate the "Booking Code" input field and type the code
            print("Typing booking code...")
            page.fill('input[placeholder="Booking Code"]', booking_code, timeout=10000)
            
            # Click the "Load" button
            print("Clicking Load button...")
            page.click('button:has-text("Load")', timeout=10000)
            
            # Wait for the betslip matches to render on the screen
            print("Waiting for network...")
            try:
                page.wait_for_selector('.m-bet-wrapper', timeout=15000)
            except Exception:
                print("Could not find .m-bet-wrapper, slip might be empty or invalid.")
            
            # Scrape ALL the raw text from the betslip container
            print("Extracting betslip text...")
            try:
                betslip_raw_text = page.locator('.m-betslip-wrapper').inner_text(timeout=5000)
            except Exception:
                print("Could not find .m-betslip-wrapper. Grabbing right sidebar as fallback...")
                betslip_raw_text = page.locator('.s-right').inner_text(timeout=5000)
            
            browser.close()
            
            if not betslip_raw_text:
                return {"booking_status": "failed", "error": "No text found on betslip."}
                
            return parse_betslip_with_ai(betslip_raw_text)
            
        except Exception as e:
            print(f"❌ Scraper failed: {e}")
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
          "user_selected_bet": "string (e.g., 'Over 2.5 Goals', 'Home Win', 'GG/BTTS')"
        }
      ]
    }

    *** EXTRACTION RULES ***
    1. Clean the team names. If the raw text says "Man Utd (Reserves)", simplify it to "Manchester United". 
    2. Try your best to extract the exact betting market the user chose from the messy text. Ensure it is readable and standard (e.g., "1X2: X" -> "Draw").
    3. If the text does not contain any recognizable football matches, set "booking_status" to "failed".
    4. Do not include any conversational text. Output only the requested JSON.
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
