import os
import requests
import threading
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ← Read from environment variable (recommended)
if not BOT_TOKEN:
    BOT_TOKEN = "8679659340:AAFDka-7x6doy5e_9areii48bKXOy5Egh-s"  # fallback

API_URL = "https://lms.mersamedia.org/api_assignment_tracking.php?key=MMI_SECRET_2026"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
}
# ===========================================

async def fetch_data():
    try:
        response = requests.get(API_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ API Error: {e}")
        return None


def format_time_ago(minutes_past: int) -> str:
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


def minutes_to_human_late(minutes: int) -> str:
    if minutes <= 0:
        return "On time"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} late"
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
        days = mins // 1440
        if days <= 5:
            active_count += 1
            short_title = ass["title"][:38] + "..." if len(ass["title"]) > 38 else ass["title"]
            keyboard.append([InlineKeyboardButton(f"📌 {short_title}", callback_data=f"ass_{ass['assignment_id']}")])
    if not keyboard:
        keyboard.append([InlineKeyboardButton("No recent assignments (≤5 days)", callback_data="none")])
    keyboard.append([InlineKeyboardButton("📋 View All Assignments", callback_data="all_assignments")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh Data", callback_data="refresh")])
    return InlineKeyboardMarkup(keyboard), active_count


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching latest assignment data...")
    data = await fetch_data()
    if not data or "assignments" not in data:
        await update.message.reply_text("❌ Could not fetch data from server.")
        return
    context.bot_data["assignment_data"] = data
    keyboard, active = create_assignment_buttons(data["assignments"])
    text = f"📚 **Active Assignments** ({active})\nDeadline passed 5 days or less\n\nPlease select an assignment:"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.bot_data.get("assignment_data")
    if not data:
        data = await fetch_data()
        if data:
            context.bot_data["assignment_data"] = data

    if not data or "assignments" not in data:
        await query.edit_message_text("❌ No data available.\nUse /start")
        return

    action = query.data
    assignments = data["assignments"]

    if action == "refresh":
        data = await fetch_data()
        if data:
            context.bot_data["assignment_data"] = data
            keyboard, _ = create_assignment_buttons(data["assignments"])
            await query.edit_message_text("✅ Data refreshed successfully!", reply_markup=keyboard)
        return

    if action == "all_assignments":
        text = "📋 **All Assignments**\n\n"
        for ass in assignments:
            time_str = format_time_ago(ass.get("minutes_past", 0))
            rate = round(ass["statistics"].get("submission_rate", 0), 1)
            text += f"**{ass['title']}**\n⏰ {time_str}\n📈 Rate: {rate}%\n\n"
        kb = [[InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    if action == "back_to_list":
        keyboard, _ = create_assignment_buttons(assignments)
        await query.edit_message_text("📚 Select an assignment:", reply_markup=keyboard)
        return

    if action.startswith("ass_"):
        ass_id = int(action[4:])
        selected = next((a for a in assignments if a["assignment_id"] == ass_id), None)
        if not selected:
            await query.edit_message_text("Assignment not found.")
            return
        context.bot_data["selected_assignment"] = selected
        time_str = format_time_ago(selected.get("minutes_past", 0))
        text = f"✅ **{selected['title']}**\n⏰ {time_str}\n\nWhat do you want to see?"
        keyboard = [
            [InlineKeyboardButton("📊 Summary", callback_data="summary_this")],
            [InlineKeyboardButton("❌ Missing & Late", callback_data="missing_this")],
            [InlineKeyboardButton("⏳ Remaining Time", callback_data="remaining_this")],
            [InlineKeyboardButton("⬅ Back to List", callback_data="back_to_list")],
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Detail screens
    if action in ["summary_this", "missing_this", "remaining_this", "back_to_selected"]:
        ass = context.bot_data.get("selected_assignment")
        if not ass:
            await query.edit_message_text("❌ No assignment selected.")
            return

        time_str = format_time_ago(ass.get("minutes_past", 0))

        if action == "summary_this":
            stats = ass["statistics"]
            rate = round(stats.get("submission_rate", 0), 1)
            total = stats.get("submitted_count", 0) + stats.get("not_submitted_count", 0)
            text = f"📊 **Summary**\n**{ass['title']}**\n⏰ {time_str}\n\n✅ Submitted: {stats.get('submitted_count', 0)}/{total}\n📈 Rate: {rate}%"
            kb = [[InlineKeyboardButton("⬅ Back", callback_data="back_to_selected")]]

        elif action == "missing_this":
            text = f"❌ **Missing & Late Submissions**\n**{ass['title']}**\n\n"
            late_list = ass["submissions"].get("late", [])
            not_sub_list = ass["submissions"].get("not_submitted", [])
            if late_list:
                text += "🟠 **Late Submissions:**\n"
                for s in late_list:
                    late_min = s.get("late_by_minutes", 0)
                    text += f"• {s['trainee_name']} — **{minutes_to_human_late(late_min)}**\n"
                text += "\n"
            if not_sub_list:
                text += "🔴 **Not Submitted:**\n"
                for s in not_sub_list:
                    text += f"• {s['trainee_name']}\n"
            if not late_list and not not_sub_list:
                text += "🎉 Great job! Everyone submitted on time."
            kb = [[InlineKeyboardButton("⬅ Back", callback_data="back_to_selected")]]

        else:  # remaining_this or back_to_selected
            text = f"⏳ **Remaining Time**\n**{ass['title']}**\n\nDeadline passed **{time_str}** ago."
            kb = [[InlineKeyboardButton("⬅ Back", callback_data="back_to_selected")]]

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    print("🚀 Assignment Tracking Bot is running...")
    print("Type /start in Telegram")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    # Keep-alive for free hosting
    def keep_alive():
        while True:
            print(f"[{time.strftime('%H:%M:%S')}] Bot keep-alive ping...")
            time.sleep(240)
    threading.Thread(target=keep_alive, daemon=True).start()
    main()