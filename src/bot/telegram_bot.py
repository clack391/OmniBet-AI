import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.bot.pref_manager import get_user_preference, set_user_preference

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN missing in environment.")
    sys.exit(1)

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "🚀 *Welcome to OmniBet AI!* 🚀\n\nI am your quantitative sports betting assistant. Use /settings to choose how you want to receive predictions.", parse_mode='Markdown')

@bot.message_handler(commands=['settings'])
def settings_menu(message):
    current_mode = get_user_preference(message.chat.id)
    
    markup = InlineKeyboardMarkup(row_width=2)
    btn_text = InlineKeyboardButton("📝 Text Mode", callback_data="set_mode_text")
    btn_image = InlineKeyboardButton("🖼️ Image Mode", callback_data="set_mode_image")
    markup.add(btn_text, btn_image)
    
    bot.send_message(
        message.chat.id, 
        f"⚙️ *OmniBet AI Settings*\nYour current mode: *{current_mode.upper()}*\n\nChoose how you want to receive predictions:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_mode_'))
def callback_handler(call):
    mode = call.data.replace('set_mode_', '')
    set_user_preference(call.message.chat.id, mode)
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"✅ *Preference Updated!*\nYou will now receive predictions as *{mode.upper()}*.\n\nType /settings to change again.",
        parse_mode='Markdown'
    )
    bot.answer_callback_query(call.id, f"Delivery mode set to {mode}")

if __name__ == "__main__":
    print("🤖 OmniBet AI Telegram Bot is starting (Polling)...")
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
