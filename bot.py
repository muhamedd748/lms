import os
import asyncio
import time
import logging
import threading
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, MenuButtonCommands
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import httpx

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    BOT_TOKEN = "8679659340:AAFyjVDpaX8RcVYwJ8WK5Dj7oS9OKf5xibU"

CHANNEL_USERNAME = "@lmsmersa"
ALLOWED_USERNAME = "muhamedd823"   # ← Your username without @

API_URL = "https://lms.mersamedia.org/api_assignment_tracking.php?key=MMI_SECRET_2026"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://lms.mersamedia.org/",
}

# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== RESTRICTION DECORATOR ==================
def restricted(func):
    """Only allow your username to use the bot"""
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.username != ALLOWED_USERNAME:
            if user:
                logger.warning(f"Unauthorized access attempt by @{user.username} (ID: {user.id})")
                try:
                    await update.message.reply_text(
                        "❌ **Access Denied**\n\n"
                        "This bot is private and can only be used by the owner."
                    )
                except:
                    pass
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ================== UTILITIES (unchanged) ==================
def format_time_ago(minutes_past: int) -> str:
    minutes_past = abs(minutes_past)
    if minutes_past < 60:
        return f"{minutes_past} minute{'s' if minutes_past != 1 else ''} ago"
    hours = minutes_past // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''} ago"
    weeks = days // 7
    return f"{weeks} week{'s' if weeks != 1 else ''} ago"

# ... (keep all your other format functions: format_remaining_time, minutes_to_human_late, create_assignment_buttons)

# ================== FETCH DATA (unchanged) ==================
async def fetch_data():
    # ... your existing fetch_data function (no changes needed)
    try:
        logger.info("🔄 Fetching data from LMS API...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(6):
                if attempt > 0:
                    await asyncio.sleep(random.uniform(1.5, 3.5))
                response = await client.get(API_URL, headers=HEADERS)
                logger.info(f"📡 Attempt {attempt+1}/6 | Status: {response.status_code}")
                raw_text = response.text.strip()
                if not raw_text:
                    logger.warning("Empty body received from server")
                    continue
                if raw_text.startswith('<html'):
                    logger.error("🚫 Server returned HTML (captcha or protection)")
                    continue
                try:
                    data = response.json()
                    count = len(data.get("assignments", []))
                    logger.info(f"✅ SUCCESS! Loaded {count} assignments")
                    return data
                except Exception as je:
                    logger.error(f"JSON parse failed: {je}")
                    continue
            logger.error("❌ All attempts failed")
            return None
    except Exception as e:
        logger.error(f"❌ Fetch error: {e}")
        return None

# ================== SEND TO CHANNEL ==================
async def send_to_channel(context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        logger.info("✅ Sent to @lmsmersa")
    except Exception as e:
        logger.error(f"Channel send failed: {e}")

# ================== MAIN MENU ==================
@restricted
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    # ... your existing show_main_menu (no big changes, just wrapped)
    data = context.bot_data.get("assignment_data") or await fetch_data()
    if data and "assignments" in data:
        context.bot_data["assignment_data"] = data

    if not data or "assignments" not in data:
        text = "❌ Could not load assignments right now.\n\nPlease click **🔄 Refresh Data**"
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
        return

    keyboard, active = create_assignment_buttons(data["assignments"])
    text = f"📚 **Active Assignments** ({active})\n_Deadline passed within last 5 days_\n\nSelect an assignment:"

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ================== BUTTON HANDLER ==================
@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... your existing button_handler code (keep everything the same)
    query = update.callback_query
    await query.answer()
    action = query.data

    if action in ["back_to_list", "refresh"]:
        await show_main_menu(update, context, edit=True)
        return

    # ... rest of your button logic (summary_this, missing_this, remaining_this, send_to_channel, etc.)
    # No changes needed here except the decorator at the top

    # (paste your full button_handler body here)

# ================== START COMMAND ==================
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context, edit=False)

# ================== POST INIT ==================
async def post_init(application):
    commands = [BotCommand("start", "📚 Show Active Assignments")]
    await application.bot.set_my_commands(commands)
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("✅ Commands set")

# ================== MAIN ==================
async def main_async():
    logger.info("🚀 Starting Assignment Tracking Bot...")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    async def error_handler(update, context):
        logger.error(f"Error: {context.error}")

    application.add_error_handler(error_handler)
    application.post_init = post_init

    await application.initialize()
    await application.start()
    logger.info("✅ Bot polling started")

    try:
        await application.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()
    finally:
        await application.stop()

if __name__ == "__main__":
    def keep_alive():
        while True:
            logger.info(f"[{time.strftime('%H:%M:%S')}] Keep-alive")
            time.sleep(300)

    threading.Thread(target=keep_alive, daemon=True).start()

    try:
        asyncio.run(main_async())
    except Exception as e:
        logger.error(f"Critical: {e}")
