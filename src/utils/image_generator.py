from PIL import Image, ImageDraw, ImageFont
import os
import uuid
import time
from datetime import datetime
from src.utils.time_utils import to_wat

def abbreviate_verdict(text):
    """
    Abbreviates common betting terms to save space in the grid.
    """
    if not text: return ""
    mappings = {
        "SECOND HALF": "2H",
        "FIRST HALF": "1H",
        "BET BUILDER": "BB",
        "OVER": ">",
        "UNDER": "<",
        "GOALS": "G",
        "DOUBLE CHANCE": "DC",
        "YES": "Y",
        "NO": "N",
        "DRAW NO BET": "DNB",
        "HALF TIME": "HT",
        "FULL TIME": "FT"
    }
    result = text.upper()
    for long, short in mappings.items():
        result = result.replace(long, short)
    # Cleanup extra spaces if e.g. "OVER 0.5" becomes "> 0.5"
    return " ".join(result.split())

def cleanup_temp_cards(max_age_hours=24):
    """
    Deletes temporary prediction cards older than max_age_hours to save storage.
    """
    temp_dir = "assets/temp_cards"
    if not os.path.exists(temp_dir):
        return
    
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    
    cleaned_count = 0
    try:
        for filename in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, filename)
            # Skip the 'latest' convenience file if needed, or just let it stay
            if filename == "latest_prediction.png":
                continue
                
            if os.path.isfile(file_path):
                file_age = os.path.getmtime(file_path)
                if file_age < cutoff:
                    os.remove(file_path)
                    cleaned_count += 1
        if cleaned_count > 0:
            print(f"🧹 Storage Guard: Cleaned up {cleaned_count} old prediction cards.")
    except Exception as e:
        print(f"⚠️ Storage Guard Error: {e}")


def generate_accumulator_card(matches_list, output_filename=None):
    """
    Generates a high-resolution Cyber-Grid tabular card for betting slips.
    """
    # Run a quick cleanup check
    cleanup_temp_cards(max_age_hours=24)

    # Ensure temp directory exists
    temp_dir = "assets/temp_cards"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir, exist_ok=True)

    # Use unique filename to avoid collision on EC2
    if output_filename is None:
        unique_id = uuid.uuid4().hex[:8]
        output_filename = os.path.join(temp_dir, f"prediction_{unique_id}.png")
    
    template_path = "assets/templates/template.png"
    
    # 1. Canvas Height Strategy
    # Dynamic algorithm: Extend if many matches, otherwise stick to min 1080
    required_height = 250 + (len(matches_list) * 100) + 150
    canvas_height = max(1080, required_height)
    canvas_width = 1080
    
    img = Image.new('RGB', (canvas_width, canvas_height), color="#0A0F1C")
    
    # Try to paste template for top background decoration
    try:
        if os.path.exists(template_path):
            template = Image.open(template_path)
            # Only crop if template is taller than canvas, otherwise paste at 0,0
            if template.height > canvas_height:
                template = template.crop((0, 0, 1080, canvas_height))
            img.paste(template, (0, 0))
    except:
        pass

    draw = ImageDraw.Draw(img)
    
    # 2. Grid Coordinates (X-Coordinates)
    match_x = 50   # Left-aligned
    verdict_x = 520 # Shifted left to provide more space for verdicts
    odds_x = 1030  # Right-aligned
    center_x = 540
    
    # ... (Font loading logic remains same) ...
    # 3. Font Loading
    font_path = "font.ttf"
    try:
        if not os.path.exists(font_path):
            header_font = row_font = date_font = total_font = ImageFont.load_default()
        else:
            header_font = ImageFont.truetype(font_path, 35)
            row_font = ImageFont.truetype(font_path, 25) # Reduced size to prevent bleed
            date_font = ImageFont.truetype(font_path, 18) # Smaller font for the date
            total_font = ImageFont.truetype(font_path, 60)
    except:
        header_font = row_font = date_font = total_font = ImageFont.load_default()

    # 4. Header Row (Y=180)
    draw.text((match_x, 180), "MATCH", fill="white", font=header_font, anchor="ls", stroke_width=3, stroke_fill="black")
    draw.text((verdict_x + 60, 180), "VERDICT", fill="#00FF00", font=header_font, anchor="ms", stroke_width=3, stroke_fill="black")
    draw.text((odds_x, 180), "ODDS", fill="#00FF00", font=header_font, anchor="rs", stroke_width=3, stroke_fill="black")

    # Header Divider (Y=200)
    draw.line([(50, 200), (1030, 200)], fill="white", width=3)

    # 5. Row Loop (Start Y=280)
    current_y = 280
    total_val = 1.0
    
    for match in matches_list:
        m_name = match.get("match", "Unknown Match")
        m_pick = match.get("pick", match.get("selection", "N/A"))
        m_market = match.get("market", "")
        m_date = match.get("match_date", "")
        
        # Format date for image if it looks like ISO
        formatted_time = ""
        if m_date and 'T' in m_date:
            try:
                # Basic parse to get HH:MM and DD/MM
                dt = datetime.fromisoformat(m_date.replace('Z', '+00:00'))
                # Convert to WAT for Nigerian users
                dt_wat = to_wat(dt)
                # We'll stick to a simple clean format for the small space
                formatted_time = dt_wat.strftime("%d/%m %H:%M WAT")
            except: formatted_time = ""

        # Merge market into pick for clarity (e.g. "BTS" + "Yes" -> "BTS Yes")
        if m_market and m_market.upper() not in m_pick.upper():
            m_pick = f"{m_market} {m_pick}".strip()
            
        try:
            m_odds = float(match.get("odds", 1.0))
        except:
            m_odds = 1.0
        
        total_val *= m_odds
        
        # A. Smart Abbreviation and Strategic Truncation
        m_pick = abbreviate_verdict(m_pick)
        
        if len(m_name) > 28: m_name = m_name[:25] + "..."
        if len(m_pick) > 28: m_pick = m_pick[:25] + "..."
        
        # B. Draw Columns
        # Match Name
        draw.text((match_x, current_y), m_name.upper(), fill="white", font=row_font, anchor="ls", stroke_width=3, stroke_fill="black")
        # Match Date (directly under name if exists)
        if formatted_time:
            draw.text((match_x, current_y + 25), formatted_time, fill="#AAAAAA", font=date_font, anchor="ls", stroke_width=1, stroke_fill="black")

        draw.text((verdict_x, current_y), m_pick.upper(), fill="#00FF00", font=row_font, anchor="ls", stroke_width=3, stroke_fill="black")
        draw.text((odds_x, current_y), f"{m_odds:.2f}", fill="white", font=row_font, anchor="rs", stroke_width=3, stroke_fill="black")
        
        # C. Sub-line divider (Y+55 instead of +45 to make room for date)
        draw.line([(50, current_y + 55), (1030, current_y + 55)], fill="#555555", width=1)
        
        # D. Move to next row
        current_y += 100

    # 6. Footer: Total Odds (Centered, pinned to bottom)
    is_single = len(matches_list) == 1
    
    # Use a cleaner, smaller size for the total odds to avoid dominating the card
    try:
        footer_font = ImageFont.truetype(font_path, 35)
    except:
        footer_font = ImageFont.load_default()
        
    # Pin to absolute bottom to avoid background clashing and middle overlap
    total_y = canvas_height - 120
        
    # Ensure footer doesn't run off
    if total_y > canvas_height - 60:
        total_y = canvas_height - 60
        
    label = "ODDS:" if is_single else "TOTAL ACCUMULATOR ODDS:"
    total_text = f"{label} {total_val:.2f}"
    draw.text((center_x, total_y), total_text, fill="#00FF00", font=footer_font, anchor="mm", stroke_width=4, stroke_fill="black")

    # 7. Save
    save_path = os.path.abspath(output_filename)
    img.save(save_path)
    return save_path

if __name__ == "__main__":
    test_accumulator = [
        {"match": "KOCAELISPOR VS KONYASPOR", "pick": "YES", "market": "BTS", "odds": 1.95, "match_date": "2024-03-20T18:00:00Z"},
        {"match": "ADANA DEMIRSPOR VS SERIKSPOR A.S", "pick": "AWAY", "market": "DOUBLE CHANCE", "odds": 1.25, "match_date": "2024-03-20T19:00:00Z"},
        {"match": "Arsenal vs Chelsea", "pick": "Home Win", "odds": 1.85, "match_date": "2024-03-20T20:00:00Z"}
    ]
    generate_accumulator_card(test_accumulator, output_filename="/tmp/acc_test.png")
    print("✅ Cyber-Grid accumulator card generated (/tmp/acc_test.png)!")
    
    # Test single game with long market (e.g. SECOND HALF OVER 0.5)
    test_single = [{"match": "Real Madrid vs Barcelona", "pick": "OVER 0.5", "market": "SECOND HALF", "odds": 1.95}]
    generate_accumulator_card(test_single, output_filename="/tmp/single_test.png")
    print("✅ Single-game grid card generated (/tmp/single_test.png)!")


