from PIL import Image, ImageDraw, ImageFont
import os
import uuid
from datetime import datetime

def format_match_date(date_val):
    """
    Formats various date inputs into a clean string.
    """
    if not date_val:
        return ""
    if isinstance(date_val, str):
        # Handle ISO strings or already formatted strings
        try:
            if 'T' in date_val:
                dt = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
                return dt.strftime("%d %b | %I:%M %p")
            return date_val # If already formatted
        except:
            return date_val
    return ""

def generate_betting_card(match_data):
    """
    Generates a 1080x1080 betting card image for Telegram with per-match timestamp above team name.
    """
    template_path = "assets/templates/template.png"
    temp_dir = "assets/temp_cards"
    os.makedirs(temp_dir, exist_ok=True)
    output_filename = os.path.join(temp_dir, f"prediction_{uuid.uuid4().hex[:8]}.png")
    
    # 1. Open Template
    try:
        if not os.path.exists(template_path):
            img = Image.new('RGB', (1080, 1080), color=(10, 15, 28))
            print(f"⚠️ {template_path} not found. Using a dark background fallback.")
        else:
            img = Image.open(template_path)
    except Exception as e:
        print(f"❌ Error opening template: {e}")
        img = Image.new('RGB', (1080, 1080), color=(10, 15, 28))

    draw = ImageDraw.Draw(img)
    center_x = 540

    # 2. Font Loading
    font_path = "font.ttf"
    try:
        if not os.path.exists(font_path):
            title_font = ImageFont.load_default()
            pick_font = ImageFont.load_default()
            date_font = ImageFont.load_default()
            match_date_font = ImageFont.load_default()
        else:
            title_font = ImageFont.truetype(font_path, 55)
            pick_font = ImageFont.truetype(font_path, 80)
            date_font = ImageFont.truetype(font_path, 25)
            match_date_font = ImageFont.truetype(font_path, 30)
    except Exception as e:
        print(f"⚠️ Error loading font {font_path}: {e}")
        title_font = ImageFont.load_default()
        pick_font = ImageFont.load_default()
        date_font = ImageFont.load_default()
        match_date_font = ImageFont.load_default()

    # 3. Data Extraction
    match_title = match_data.get("match", "Unknown Match")
    match_date = format_match_date(match_data.get("match_date") or match_data.get("date"))
    
    sc = match_data.get("supreme_court", {})
    av = match_data.get("audit_verdict", {})
    
    if sc and sc.get("primary_safe_pick"):
        pick_tip = sc["primary_safe_pick"].get("tip", "N/A")
        odds = sc["primary_safe_pick"].get("odds", "0.00")
    elif av and av.get("ai_recommended_bet"):
        pick_tip = av.get("ai_recommended_bet", "N/A")
        odds = av.get("estimated_odds", "0.00")
    else:
        pick_tip = match_data.get("primary_pick", {}).get("tip", match_data.get("safe_bet_tip", "N/A"))
        odds = match_data.get("primary_pick", {}).get("odds", match_data.get("confidence", "0.00"))

    # 4. Drawing Content
    current_time_str = datetime.now().strftime("%d %b %Y | %I:%M %p")
    
    # Global Header
    draw.text((center_x, 80), "OMNIBET AI PREDICT", fill="#00FF00", font=title_font, anchor="mm", stroke_width=4, stroke_fill="black")
    draw.text((center_x, 125), current_time_str, fill="#CCCCCC", font=date_font, anchor="mm", stroke_width=2, stroke_fill="black")

    # Match Block (Date moved ABOVE Team Name)
    draw.text((center_x, 230), "MATCH:", fill="white", font=title_font, anchor="mm", stroke_width=4, stroke_fill="black")
    if match_date:
        draw.text((center_x, 290), match_date.upper(), fill="#CCCCCC", font=match_date_font, anchor="mm", stroke_width=2, stroke_fill="black")
        draw.text((center_x, 370), match_title.upper(), fill="white", font=pick_font, anchor="mm", stroke_width=4, stroke_fill="black")
    else:
        draw.text((center_x, 350), match_title.upper(), fill="white", font=pick_font, anchor="mm", stroke_width=4, stroke_fill="black")
    
    # Verdict Block
    draw.text((center_x, 600), "SUPREME COURT VERDICT:", fill="white", font=title_font, anchor="mm", stroke_width=4, stroke_fill="black")
    draw.text((center_x, 720), pick_tip.upper(), fill="#00FF00", font=pick_font, anchor="mm", stroke_width=4, stroke_fill="black")
    draw.text((center_x, 850), f"ODDS: {odds}", fill="#00FF00", font=pick_font, anchor="mm", stroke_width=4, stroke_fill="black")

    # 5. Save
    save_path = os.path.abspath(output_filename)
    img.save(save_path)
    latest_path = os.path.abspath("latest_prediction.png")
    img.save(latest_path)
    return save_path

def generate_accumulator_card(bets):
    """
    Generates a dynamic accumulator card with match dates positioned above team names.
    """
    template_path = "assets/templates/template.png"
    temp_dir = "assets/temp_cards"
    os.makedirs(temp_dir, exist_ok=True)
    output_filename = os.path.join(temp_dir, f"accumulator_{uuid.uuid4().hex[:8]}.png")
    
    required_height = 250 + (len(bets) * 220) + 150
    canvas_height = max(1080, required_height)
    
    background_color = "#0A0F1C"
    img = Image.new('RGB', (1080, canvas_height), color=background_color)
    
    try:
        if os.path.exists(template_path):
            template = Image.open(template_path)
            template = template.crop((0, 0, 1080, min(1080, canvas_height)))
            img.paste(template, (0, 0))
    except Exception as e:
        pass

    draw = ImageDraw.Draw(img)
    center_x = 540
    
    font_path = "font.ttf"
    try:
        if not os.path.exists(font_path):
            header_font = title_font = pick_font = date_font = match_date_font = ImageFont.load_default()
        else:
            header_font = ImageFont.truetype(font_path, 60)
            title_font = ImageFont.truetype(font_path, 35)
            pick_font = ImageFont.truetype(font_path, 45)
            date_font = ImageFont.truetype(font_path, 25)
            match_date_font = ImageFont.truetype(font_path, 22)
    except:
        header_font = title_font = pick_font = date_font = match_date_font = ImageFont.load_default()

    # Global Header
    current_time_str = datetime.now().strftime("%d %b %Y | %I:%M %p")
    draw.text((center_x, 80), "ELITE ACCUMULATOR", fill="#00FF00", font=header_font, anchor="mm", stroke_width=4, stroke_fill="black")
    draw.text((center_x, 135), current_time_str, fill="#CCCCCC", font=date_font, anchor="mm", stroke_width=2, stroke_fill="black")
    
    # Dynamic Loop Layout
    current_y = 220
    total_odds = 1.0
    
    for bet in bets:
        match_title = bet.get("match", "Unknown Match")
        if len(match_title) > 40: match_title = match_title[:37] + "..."
        
        match_date = format_match_date(bet.get("match_date") or bet.get("date"))
        pick = bet.get("selection", "N/A")
        try:
            val_odds = float(bet.get("odds", 1.0))
        except:
            val_odds = 1.0
        
        total_odds *= val_odds
        
        # Match Date moved ABOVE Team Name
        if match_date:
            draw.text((center_x, current_y), match_date.upper(), fill="#888888", font=match_date_font, anchor="mm", stroke_width=2, stroke_fill="black")
            draw.text((center_x, current_y + 40), match_title.upper(), fill="white", font=title_font, anchor="mm", stroke_width=3, stroke_fill="black")
            off_y = 95
        else:
            draw.text((center_x, current_y + 20), match_title.upper(), fill="white", font=title_font, anchor="mm", stroke_width=3, stroke_fill="black")
            off_y = 75
        
        # Tip @ Odds Line
        pick_line = f"{pick.upper()} @ {val_odds:.2f}"
        draw.text((center_x, current_y + off_y), pick_line, fill="#00FF00", font=pick_font, anchor="mm", stroke_width=3, stroke_fill="black")
        
        # Divider
        draw.line((250, current_y + off_y + 60, 830, current_y + off_y + 60), fill="#333333", width=2)
        
        current_y += 220

    # Footer
    footer_y = current_y - 120
    footer_text = f"TOTAL ACCUMULATOR ODDS: {total_odds:.2f}"
    draw.text((center_x, footer_y + 100), footer_text, fill="#00FF00", font=pick_font, anchor="mm", stroke_width=4, stroke_fill="black")

    save_path = os.path.abspath(output_filename)
    img.save(save_path)
    latest_path = os.path.abspath("latest_prediction.png")
    img.save(latest_path)
    print(f"✅ Card with match dates repositioned: {save_path}")
    return save_path

if __name__ == "__main__":
    # Test single
    test_single = {
        "match": "Arsenal vs Chelsea",
        "match_date": "2026-03-14T15:00:00Z",
        "primary_pick": {"tip": "Home Win", "odds": 1.75}
    }
    generate_betting_card(test_single)
    
    # Test accumulator
    test_bets = [
        {"match": "USM KHENCHELA VS JS KABYLIE", "selection": "X2", "odds": 1.44, "match_date": "2026-03-13T19:00:00Z"},
        {"match": "Arsenal vs Chelsea", "selection": "Home Win", "odds": 1.85, "match_date": "14 Mar 2026 | 03:00 PM"}
    ]
    generate_accumulator_card(test_bets)
