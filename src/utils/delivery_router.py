import telebot
import os
import time
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo # For older python
from src.bot.pref_manager import get_user_preference
from src.utils.image_generator import generate_accumulator_card

# Global bot instance to avoid re-initializing
_bot_instance = None

def get_bot():
    global _bot_instance
    if _bot_instance is None:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            return None
        _bot_instance = telebot.TeleBot(token)
    return _bot_instance

def deliver_prediction(chat_id, match_data, retries=2):
    """
    Routes a single prediction to a user based on their preferred delivery mode.
    """
    bot = get_bot()
    if not bot:
        print("❌ TELEGRAM_BOT_TOKEN missing in environment.")
        return False

    mode = get_user_preference(chat_id)
    match_name = match_data.get("match", "Unknown Match")
    
    # Extract pick & market details
    sc = match_data.get("supreme_court", {})
    av = match_data.get("audit_verdict", {})
    
    pick_tip = "N/A"
    odds = "0.00"
    market = ""
    
    if sc and (sc.get("Arbiter_Safe_Pick") or sc.get("primary_safe_pick")):
        asp = sc.get("Arbiter_Safe_Pick") or sc.get("primary_safe_pick")
        pick_tip = asp.get("tip", "N/A")
        odds = asp.get("odds", "0.00")
        market = asp.get("market", "")
    elif av and av.get("ai_recommended_bet"):
        pick_tip = av.get("ai_recommended_bet", "N/A")
        odds = av.get("estimated_odds", "0.00")
        market = av.get("market", "")
    else:
        # Fallback to standard prediction paths
        pk = match_data.get("primary_pick", {})
        pick_tip = pk.get("tip", match_data.get("safe_bet_tip", "N/A"))
        odds = pk.get("odds", match_data.get("confidence", "0.00"))
        market = pk.get("market", match_data.get("bet_option", "")) # Try both

    # Combine Market + Tip for text context
    full_pick = f"{market} {pick_tip}".strip() if market else pick_tip

    # Extract date
    match_date = match_data.get("match_date", "")
    formatted_date = ""
    if match_date:
        try:
            dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
            dt_wat = dt.astimezone(ZoneInfo("Africa/Lagos"))
            formatted_date = dt_wat.strftime("%Y-%m-%d %H:%M WAT")
        except: formatted_date = str(match_date)

    if mode == 'image':
        for attempt in range(retries + 1):
            try:
                # Universal Cyber-Grid format
                image_path = generate_accumulator_card([{
                    "match": match_name,
                    "pick": pick_tip,
                    "odds": odds,
                    "market": market,
                    "match_date": match_date # Pass through to generator
                }])
                caption = f"🏆 *{match_name}*\n"
                if formatted_date:
                    caption += f"📅 Match Time: *{formatted_date}*\n"
                caption += f"⚖️ Supreme Court Verdict: *{full_pick}*\n📈 Odds: *{odds}*"
                
                with open(image_path, 'rb') as photo:
                    bot.send_photo(chat_id, photo, caption=caption, parse_mode='Markdown', timeout=20)
                return True
            except Exception as e:
                print(f"⚠️ Attempt {attempt + 1} failed sending image: {e}")
                if attempt < retries:
                    time.sleep(1)
                    continue
                else:
                    mode = 'text'

    if mode == 'text':
        try:
            text = (
                f"🔥 *OMNIBET AI PREDICTION* 🔥\n\n"
                f"⚽ *Match:* {match_name}\n"
            )
            if formatted_date:
                text += f"📅 *Time:* {formatted_date}\n"
            
            text += (
                f"⚖️ *Supreme Court Verdict:* _{full_pick}_\n"
                f"📈 *Odds:* `{odds}`\n\n"
                f"🔗 _Analyze more at OmniBet AI Dashboard_"
            )
            bot.send_message(chat_id, text, parse_mode='Markdown', timeout=10)
            return True
        except Exception as e:
            print(f"❌ Error sending text prediction: {e}")
            return False

    return False

def deliver_accumulator(chat_id, bets, total_odds, retries=2):
    """
    Delivers a consolidated multi-bet prediction.
    """
    bot = get_bot()
    if not bot:
        return False

    mode = get_user_preference(chat_id)
    
    if mode == 'image':
        for attempt in range(retries + 1):
            try:
                image_path = generate_accumulator_card(bets)
                caption = f"🔥 *ELITE ACCUMULATOR* 🔥\n📊 Matches: {len(bets)}\n📈 Total Odds: *{total_odds:.2f}x*\n\n🚀 _Join the winning side with OmniBet AI_"
                with open(image_path, 'rb') as photo:
                    bot.send_photo(chat_id, photo, caption=caption, parse_mode='Markdown', timeout=30)
                return True
            except Exception as e:
                print(f"⚠️ Accumulator image attempt {attempt + 1} failed: {e}")
                if attempt < retries:
                    time.sleep(1)
                    continue
                else:
                    mode = 'text'

    if mode == 'text':
        try:
            text = f"🔥 *OMNIBET AI ACCUMULATOR* 🔥\n\n"
            for bet in bets:
                market = bet.get("market", "")
                pick = bet.get("selection", "N/A")
                full_pick = f"{market.upper()} {pick}" if market and market.upper() not in pick.upper() else pick
                
                # Format date for text
                m_date = bet.get("match_date", "")
                f_date = ""
                if m_date:
                    try:
                        dt = datetime.fromisoformat(m_date.replace('Z', '+00:00'))
                        dt_wat = dt.astimezone(ZoneInfo("Africa/Lagos"))
                        f_date = dt_wat.strftime("%d/%m %H:%M WAT")
                    except: pass

                text += f"⚽ *{bet.get('match', 'Match')}*\n"
                if f_date:
                    text += f"📅 _{f_date}_\n"
                text += f"⚖️ Pick: _{full_pick}_ | Odds: `{bet.get('odds', '0.00')}`\n\n"
            text += f"💰 *Total Odds: {total_odds:.2f}x*\n\n"
            text += "⚡ _Generated by OmniBet AI Engine_"
            bot.send_message(chat_id, text, parse_mode='Markdown', timeout=15)
            return True
        except Exception as e:
            print(f"❌ Error sending consolidated text: {e}")
            return False

    return False
