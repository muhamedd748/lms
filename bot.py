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

# ================== UTILITIES ==================
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
                    logger.error(f"Preview: {raw_text[:300]}")
                    continue

                try:
                    data = response.json()
                    count = len(data.get("assignments", []))
                    logger.info(f"✅ SUCCESS! Loaded {count} assignments")
                    return data
                except Exception as je:
                    logger.error(f"JSON parse failed: {je}")
                    logger.error(f"First 300 chars: {raw_text[:300]}")
                    continue

            logger.error("❌ All attempts failed - Server not returning valid JSON")
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
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    data = context.bot_data.get("assignment_data") or await fetch_data()

    if data and "assignments" in data:
        context.bot_data["assignment_data"] = data

    if not data or "assignments" not in data:
        text = "❌ Could not load assignments right now.\n\nThe server is not returning data.\nPlease click **🔄 Refresh Data** or contact admin."
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


# ================== BUTTON HANDLER (simplified for stability) ==================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action in ["back_to_list", "refresh"]:
        await show_main_menu(update, context, edit=True)
        return

    data = context.bot_data.get("assignment_data") or await fetch_data()
    if not data or "assignments" not in data:
        await query.edit_message_text("❌ No data available. Try Refresh again.")
        return

    assignments = data["assignments"]

    if action == "all_assignments":
        text = "📋 **All Assignments**\n\n"
        for ass in assignments:
            time_str = format_time_ago(ass.get("minutes_past", 0))
            rate = round(ass.get("statistics", {}).get("submission_rate", 0), 1)
            text += f"**{ass['title']}**\n⏰ {time_str}\n📈 Rate: {rate}%\n\n"
        kb = [[InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    if action.startswith("ass_"):
        try:
            ass_id = int(action[4:])
            selected = next((a for a in assignments if a.get("assignment_id") == ass_id), None)
            if not selected:
                await query.edit_message_text("Assignment not found.")
                return

            context.bot_data["selected_assignment"] = selected
            time_str = format_time_ago(abs(selected.get("minutes_past", 0)))

            text = f"✅ **{selected['title']}**\n⏰ {time_str}\n\nWhat would you like to see?"

            keyboard = [
                [InlineKeyboardButton("📊 Summary", callback_data="summary_this")],
                [InlineKeyboardButton("❌ Missing & Late", callback_data="missing_this")],
                [InlineKeyboardButton("⏳ Deadline Info", callback_data="remaining_this")],
                [InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")],
            ]
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        except Exception:
            await query.edit_message_text("Invalid selection.")
            return

    # For simplicity, keep only basic detail views
    ass = context.bot_data.get("selected_assignment")
    if not ass:
        await query.edit_message_text("❌ No assignment selected.")
        return

    minutes_past = ass.get("minutes_past", 0)
    title = ass.get("title", "Unknown Assignment")

    if action == "summary_this":
        stats = ass.get("statistics", {})
        rate = round(stats.get("submission_rate", 0), 1)
        total = stats.get("submitted_count", 0) + stats.get("not_submitted_count", 0)
        time_display = f"⏰ Deadline passed **{format_time_ago(minutes_past)}**" if minutes_past >= 0 else f"⏳ **{format_remaining_time(abs(minutes_past))} remaining**"

        text = f"📊 **Summary**\n**{title}**\n{time_display}\n\n✅ Submitted: {stats.get('submitted_count', 0)}/{total}\n📈 Rate: {rate}%"
        channel_text = f"📊 **Summary**\n**{title}**\n{time_display}\n✅ Submitted: {stats.get('submitted_count', 0)}/{total}\n📈 Rate: {rate}%"

        keyboard = [
            [InlineKeyboardButton("📢 Send to Channel", callback_data="send_to_channel")],
            [InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]
        ]
        context.bot_data["pending_channel_text"] = channel_text

    elif action == "missing_this":
        text = f"❌ **Missing & Late Submissions**\n**{title}**\n\n🎉 Feature under maintenance."
        keyboard = [[InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]]
    else:
        text = f"⏳ **Deadline Info**\n**{title}**\n\nUnder maintenance."
        keyboard = [[InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]]

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    if action == "send_to_channel":
        channel_text = context.bot_data.get("pending_channel_text")
        if channel_text:
            await send_to_channel(context, channel_text)
            await query.edit_message_text("✅ Sent to @lmsmersa successfully!")
        return


# ================== POST INIT & MAIN ==================
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
