import os
import asyncio
import time
import logging
import threading

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

API_URL = "https://lms.mersamedia.org/api_assignment_tracking.php?key=MMI_SECRET_2026"

# Better headers to look more like a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://lms.mersamedia.org/",
    "Cache-Control": "no-cache"
}

# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

def format_remaining_time(minutes: int) -> str:
    minutes = abs(minutes)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {mins} minute{'s' if mins != 1 else ''}"

def minutes_to_human_late(minutes: int) -> str:
    if minutes <= 0:
        return "On time"
    hours = minutes // 60
    mins_left = minutes % 60
    if hours < 24:
        if mins_left == 0:
            return f"{hours} hour{'s' if hours != 1 else ''} late"
        return f"{hours} hour{'s' if hours != 1 else ''} {mins_left} minute{'s' if mins_left != 1 else ''} late"
    days = hours // 24
    hours_left = hours % 24
    if hours_left == 0:
        return f"{days} day{'s' if days != 1 else ''} late"
    return f"{days} day{'s' if days != 1 else ''} {hours_left} hour{'s' if hours_left != 1 else ''} late"

def create_assignment_buttons(assignments):
    keyboard = []
    active_count = 0
    for ass in assignments:
        mins = ass.get("minutes_past", 0)
        days = abs(mins) // 1440
        if days <= 5:
            active_count += 1
            short_title = ass["title"][:38] + "..." if len(ass["title"]) > 38 else ass["title"]
            keyboard.append([InlineKeyboardButton(f"📌 {short_title}", callback_data=f"ass_{ass['assignment_id']}")])

    if not keyboard:
        keyboard.append([InlineKeyboardButton("No recent assignments (≤5 days)", callback_data="none")])

    keyboard.append([InlineKeyboardButton("📋 View All Assignments", callback_data="all_assignments")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh Data", callback_data="refresh")])

    return InlineKeyboardMarkup(keyboard), active_count


# ================== FETCH DATA ==================
async def fetch_data():
    try:
        logger.info("🔄 Fetching data from LMS API...")

        async with httpx.AsyncClient(timeout=25.0) as client:
            for attempt in range(4):
                response = await client.get(API_URL, headers=HEADERS)
                logger.info(f"📡 Attempt {attempt+1} → Status: {response.status_code}")

                raw_text = response.text.strip()
                if not raw_text:
                    logger.warning("Empty body, retrying...")
                    await asyncio.sleep(1.5)
                    continue

                # If we get HTML (captcha), log it clearly
                if raw_text.startswith('<html'):
                    logger.error("🚫 CAPTCHA / Protection detected!")
                    logger.error(f"Raw HTML preview: {raw_text[:400]}")
                    await asyncio.sleep(2.0)
                    continue

                try:
                    data = response.json()
                    count = len(data.get("assignments", []))
                    logger.info(f"✅ SUCCESS! Loaded {count} assignments")
                    return data
                except Exception as je:
                    logger.error(f"JSON parse failed: {je}")
                    await asyncio.sleep(1.0)
                    continue

            logger.error("❌ All attempts failed")
            return None

    except Exception as e:
        logger.error(f"❌ Fetch error: {e}")
        return None


# ================== SEND TO CHANNEL (unchanged) ==================
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


# ================== MAIN MENU & BUTTON HANDLER (same as your last working version) ==================
# ... (I kept them exactly as in your last message to avoid new bugs)

# Paste your previous show_main_menu and button_handler here (the ones with Summary remaining time logic)
# For brevity, I'm not repeating them again. Just keep the same show_main_menu and button_handler from your last code.

# If you want, reply "send full code with button_handler" and I'll give the complete file.

# For now, only replace the HEADERS and fetch_data() function with the ones above.

# ================== POST INIT & MAIN (keep as is) ==================
async def post_init(application):
    commands = [BotCommand("start", "📚 Show Active Assignments")]
    await application.bot.set_my_commands(commands)
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("✅ Commands set")

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

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await show_main_menu(update, context, edit=False)

    try:
        asyncio.run(main_async())
    except Exception as e:
        logger.error(f"Critical: {e}")
