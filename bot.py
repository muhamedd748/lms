import os
import threading
import time
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import Conflict, TelegramError

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    BOT_TOKEN = "8679659340:AAFyjVDpaX8RcVYwJ8WK5Dj7oS9OKf5xibU"  # ⚠️ REPLACE THIS

API_URL = "https://lms.mersamedia.org/api_assignment_tracking.php?key=MMI_SECRET_2026"
# ===========================================


# ✅ SAFE ASYNC FETCH
async def fetch_data():
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(API_URL)

            print("STATUS:", response.status_code)
            print("RAW:", response.text[:200])

            if response.status_code != 200:
                print("❌ Bad status code")
                return None

            text = response.text.strip()

            if not text:
                print("❌ Empty response")
                return None

            try:
                return response.json()
            except ValueError:
                print("❌ Invalid JSON")
                return None

    except httpx.TimeoutException:
        print("❌ Request timed out")
        return None

    except Exception as e:
        print(f"❌ API Error: {e}")
        return None


# ================= UTIL FUNCTIONS =================
def format_time_ago(minutes):
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hr ago"
    days = hours // 24
    return f"{days} day(s) ago"


def minutes_to_human_late(minutes):
    if minutes <= 0:
        return "On time"
    if minutes < 60:
        return f"{minutes} min late"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m late"


def create_assignment_buttons(assignments):
    keyboard = []
    count = 0

    for a in assignments:
        if a.get("minutes_past", 0) // 1440 <= 5:
            count += 1
            title = a["title"][:35] + "..." if len(a["title"]) > 35 else a["title"]
            keyboard.append([
                InlineKeyboardButton(f"📌 {title}", callback_data=f"ass_{a['assignment_id']}")
            ])

    if not keyboard:
        keyboard.append([InlineKeyboardButton("No recent assignments", callback_data="none")])

    keyboard.append([InlineKeyboardButton("📋 All Assignments", callback_data="all")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh")])

    return InlineKeyboardMarkup(keyboard), count


# ================= COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching data...")

    data = await fetch_data()

    if not data or "assignments" not in data:
        await update.message.reply_text("❌ Failed to fetch data.")
        return

    context.bot_data["data"] = data

    kb, count = create_assignment_buttons(data["assignments"])

    await update.message.reply_text(
        f"📚 Active Assignments ({count})\nSelect one:",
        reply_markup=kb
    )


# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.bot_data.get("data")

    if not data:
        data = await fetch_data()
        if data:
            context.bot_data["data"] = data

    if not data:
        await query.edit_message_text("❌ No data available.")
        return

    assignments = data["assignments"]
    action = query.data

    # 🔄 REFRESH
    if action == "refresh":
        data = await fetch_data()
        if data:
            context.bot_data["data"] = data
            kb, _ = create_assignment_buttons(data["assignments"])
            await query.edit_message_text("✅ Refreshed!", reply_markup=kb)
        else:
            await query.edit_message_text("❌ Refresh failed.")
        return

    # 📋 ALL
    if action == "all":
        text = "📋 All Assignments\n\n"
        for a in assignments:
            rate = round(a["statistics"].get("submission_rate", 0), 1)
            text += f"{a['title']}\n📈 {rate}%\n\n"

        kb = [[InlineKeyboardButton("⬅ Back", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    # ⬅ BACK
    if action == "back":
        kb, _ = create_assignment_buttons(assignments)
        await query.edit_message_text("📚 Select assignment:", reply_markup=kb)
        return

    # 📌 SINGLE ASSIGNMENT
    if action.startswith("ass_"):
        ass_id = int(action.split("_")[1])
        a = next((x for x in assignments if x["assignment_id"] == ass_id), None)

        if not a:
            await query.edit_message_text("Not found")
            return

        context.bot_data["selected"] = a

        text = f"📌 {a['title']}\nChoose option:"
        kb = [
            [InlineKeyboardButton("📊 Summary", callback_data="summary")],
            [InlineKeyboardButton("❌ Missing", callback_data="missing")],
            [InlineKeyboardButton("⬅ Back", callback_data="back")]
        ]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    # 📊 SUMMARY
    if action == "summary":
        a = context.bot_data.get("selected")

        stats = a["statistics"]
        rate = round(stats.get("submission_rate", 0), 1)

        text = (
            f"📊 {a['title']}\n\n"
            f"✅ Submitted: {stats['submitted_count']}\n"
            f"❌ Missing: {stats['not_submitted_count']}\n"
            f"📈 Rate: {rate}%"
        )

        kb = [[InlineKeyboardButton("⬅ Back", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
        return

    # ❌ MISSING
    if action == "missing":
        a = context.bot_data.get("selected")

        text = f"❌ Missing - {a['title']}\n\n"

        for s in a["submissions"]["not_submitted"]:
            text += f"• {s['trainee_name']}\n"

        kb = [[InlineKeyboardButton("⬅ Back", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


# ================= MAIN =================
def main():
    print("🚀 Bot starting...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    async def error_handler(update, context):
        if isinstance(context.error, Conflict):
            print("⚠️ Bot already running elsewhere")
        else:
            print("Error:", context.error)

    app.add_error_handler(error_handler)

    app.run_polling(drop_pending_updates=True)


# ================= KEEP ALIVE =================
def keep_alive():
    while True:
        print(f"[{time.strftime('%H:%M:%S')}] alive...")
        time.sleep(240)


if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    main()
