import os
import asyncio
import time
import logging
import threading
import random
import gzip
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
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://lms.mersamedia.org/",
    "Cache-Control": "no-cache",
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


# ================== FIXED FETCH WITH MANUAL DECOMPRESSION ==================
async def fetch_data():
    try:
        logger.info("🔄 Fetching data from LMS API...")
        await asyncio.sleep(random.uniform(1.0, 2.5))

        async with httpx.AsyncClient(timeout=40.0, follow_redirects=True) as client:
            for attempt in range(6):
                logger.info(f"📡 Attempt {attempt+1}/6")

                response = await client.get(API_URL, headers=HEADERS)

                logger.info(f"   Status: {response.status_code} | Content-Type: {response.headers.get('content-type')} | Encoding: {response.headers.get('content-encoding')}")

                if response.status_code != 200:
                    await asyncio.sleep(2)
                    continue

                # === MANUAL DECOMPRESSION FIX ===
                content = response.content
                encoding = response.headers.get("content-encoding", "").lower()

                if encoding == "gzip":
                    try:
                        content = gzip.decompress(content)
                        logger.info("   ✅ Gzip decompressed successfully")
                    except Exception as de:
                        logger.error(f"   Gzip decompress failed: {de}")
                elif encoding == "br":
                    try:
                        import brotli
                        content = brotli.decompress(content)
                        logger.info("   ✅ Brotli decompressed successfully")
                    except ImportError:
                        logger.warning("   brotli module not installed")
                    except Exception as de:
                        logger.error(f"   Brotli decompress failed: {de}")

                # Convert to text
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    text = content.decode("utf-8", errors="replace")
                    logger.warning("   Used replace for decoding")

                if len(text) < 20 or text.strip().startswith("<"):
                    logger.error("   ❌ Received HTML or empty data")
                    logger.error(f"   Preview: {text[:300]}...")
                    await asyncio.sleep(3)
                    continue

                # Parse JSON
                try:
                    data = response.json() if not encoding else __import__('json').loads(text)
                    count = len(data.get("assignments", []))
                    logger.info(f"✅ SUCCESS! Loaded {count} assignments")
                    return data
                except Exception as je:
                    logger.error(f"   JSON parse failed: {je}")
                    logger.error(f"   First 400 chars: {text[:400]}")
                    await asyncio.sleep(2)
                    continue

            logger.error("❌ All attempts failed")
            return None

    except Exception as e:
        logger.error(f"❌ Unexpected fetch error: {e}")
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
        text = "❌ Could not load assignments right now.\n\nPlease click **🔄 Refresh Data** again."
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
        if minutes_past < 0:
            time_display = f"⏳ **{format_remaining_time(abs(minutes_past))} remaining**"
        else:
            time_display = f"⏰ Deadline passed **{format_time_ago(minutes_past)}**"
        text = f"📊 **Summary**\n**{title}**\n{time_display}\n\n✅ Submitted: {stats.get('submitted_count', 0)}/{total}\n📈 Rate: {rate}%"
        channel_text = f"📊 **Assignment Summary**\n\n**{title}**\n{time_display}\n✅ Submitted: {stats.get('submitted_count', 0)}/{total}\n📈 Rate: {rate}%"
        keyboard = [
            [InlineKeyboardButton("📢 Send to Channel", callback_data="send_to_channel")],
            [InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]
        ]
        context.bot_data["pending_channel_text"] = channel_text

    elif action == "missing_this":
        submissions = ass.get("submissions", {})
        late_list = submissions.get("late", [])
        not_sub_list = submissions.get("not_submitted", [])
        text = f"❌ **Missing & Late Submissions**\n**{title}**\n\n"
        channel_text = f"❌ **Missing & Late Report**\n\n**{title}**\n⏰ {format_time_ago(abs(minutes_past))}\n\n"
        if late_list:
            text += "🟠 **Late Submissions:**\n"
            channel_text += "🟠 **Late:**\n"
            for s in late_list:
                late_min = s.get("late_by_minutes", 0)
                name = s.get("trainee_name", "Unknown")
                text += f"• {name} — **{minutes_to_human_late(late_min)}**\n"
                channel_text += f"• {name} — {minutes_to_human_late(late_min)}\n"
        if not_sub_list:
            text += "\n🔴 **Not Submitted:**\n"
            channel_text += "\n🔴 **Not Submitted:**\n"
            for s in not_sub_list:
                name = s.get("trainee_name", "Unknown")
                text += f"• {name}\n"
                channel_text += f"• {name}\n"
        if not late_list and not not_sub_list:
            text += "🎉 Everyone submitted on time!"
            channel_text += "🎉 Everyone submitted on time!"
        keyboard = [
            [InlineKeyboardButton("📢 Send to Channel", callback_data="send_to_channel")],
            [InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]
        ]
        context.bot_data["pending_channel_text"] = channel_text

    else:  # remaining_this
        if minutes_past < 0:
            time_str = format_remaining_time(abs(minutes_past))
            text = f"⏳ **Remaining Time**\n**{title}**\n\n**{time_str} remaining** until deadline."
        else:
            text = f"⏰ **Deadline Info**\n**{title}**\n\nDeadline passed **{format_time_ago(minutes_past)}** ago."
        keyboard = [[InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]]

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    if action == "send_to_channel":
        channel_text = context.bot_data.get("pending_channel_text")
        if channel_text:
            await send_to_channel(context, channel_text)
            await query.edit_message_text("✅ Sent to @lmsmersa successfully!")
        return


# ================== START & POST INIT ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context, edit=False)

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
    application.add_error_handler(lambda update, context: logger.error(f"Error: {context.error}"))

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
        logger.error(f"Critical error: {e}")
