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

# ================== IMPROVED FETCH DATA ==================
async def fetch_data():
    try:
        logger.info("🔄 Fetching data from LMS API...")
        async with httpx.AsyncClient(timeout=40.0) as client:
            for attempt in range(8):   # Increased attempts
                if attempt > 0:
                    await asyncio.sleep(random.uniform(3.0, 6.0))  # Longer delay to reduce detection

                response = await client.get(API_URL, headers=HEADERS)
                logger.info(f"📡 Attempt {attempt+1}/8 | Status: {response.status_code}")

                raw_text = response.text.strip()
                if not raw_text:
                    logger.warning("Empty body received")
                    continue

                # Strong detection for SiteGround SGCaptcha
                lower = raw_text.lower()
                if ('sgcaptcha' in lower) or ('/.well-known/sgcaptcha' in lower) or \
                   (lower.startswith(('<html', '<!doctype'))) and ('captcha' in lower or 'robot' in lower):
                    logger.error("🚫 SGCaptcha / Antibot triggered")
                    logger.error(f"Preview: {raw_text[:600]}")
                    continue

                # Try to parse JSON
                try:
                    data = response.json()
                    count = len(data.get("assignments", []))
                    logger.info(f"✅ SUCCESS! Loaded {count} assignments")
                    return data
                except Exception as je:
                    logger.error(f"JSON parse failed: {je}")
                    logger.error(f"First 400 chars: {raw_text[:400]}")
                    continue

            logger.error("❌ All attempts failed - Server blocked by protection")
            return None
    except Exception as e:
        logger.error(f"❌ Fetch error: {e}")
        return None

# ================== The rest of your code remains the same ==================
# (send_to_channel, show_main_menu, button_handler, start, post_init, main_async)

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

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    data = context.bot_data.get("assignment_data") or await fetch_data()
    if data and "assignments" in data:
        context.bot_data["assignment_data"] = data
    if not data or "assignments" not in data:
        text = "❌ Could not load assignments right now.\n\nSiteGround protection is blocking the request.\nPlease click **🔄 Refresh Data** or contact hosting support."
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

# ... [button_handler remains exactly as in your original code] ...

# Paste the rest of your original button_handler, start, post_init, main_async, and keep_alive here unchanged.

# For brevity, I kept only the changed parts above. Replace fetch
