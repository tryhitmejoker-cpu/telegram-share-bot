#!/usr/bin/env python3
import logging
import base64
import json
import os
import httpx
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
FOLDER_LINK        = os.environ["FOLDER_LINK"]
CHANNEL_ID         = int(os.environ["CHANNEL_ID"])
ADMIN_ID           = 8633029909

USED_USERS_FILE    = "used_users.json"
COUNTER_FILE       = "counter.json"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def load_used_users() -> set:
    if Path(USED_USERS_FILE).exists():
        with open(USED_USERS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_used_users(users: set):
    with open(USED_USERS_FILE, "w") as f:
        json.dump(list(users), f)

def load_counter() -> int:
    if Path(COUNTER_FILE).exists():
        with open(COUNTER_FILE, "r") as f:
            return json.load(f).get("count", 0)
    return 0

def save_counter(count: int):
    with open(COUNTER_FILE, "w") as f:
        json.dump({"count": count}, f)

async def verify_screenshot_with_ai(image_bytes: bytes) -> tuple[int, bool, str]:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = """You are a strict verification assistant for a Telegram bot.
A user claims to have shared a Telegram folder link to 3 different real Telegram channels or groups and sent a screenshot as proof.

Carefully examine the screenshot and count how many REAL channels or groups the link was shared to.

IMPORTANT RULES for counting:
- ONLY count real channels or groups with actual members
- Do NOT count: Saved Messages, bots, direct/private chats, or any chat that is clearly a bot
- The share must show the folder link being sent, not just selected
- If the screenshot does not show a Telegram share menu: count=0, valid=false

Respond ONLY with JSON, no extra text:
{"count": 3, "valid": true, "reason": "Brief reason"}

- count=0, valid=false: not a real screenshot or no real channels
- count=1, valid=false: shared to 1 real channel
- count=2, valid=false: shared to 2 real channels
- count=3, valid=true: shared to 3 or more real channels"""

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o",
                "max_tokens": 200,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                        ]
                    }
                ]
            }
        )

    if response.status_code != 200:
        logger.error(f"OpenAI API error: {response.text}")
        return 0, False, "Verification service error. Please try again later."

    data = response.json()
    raw_text = data["choices"][0]["message"]["content"].strip()
    try:
        clean = raw_text.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        count = int(result.get("count", 0))
        valid = bool(result.get("valid", False))
        reason = result.get("reason", "No reason provided")
        return count, valid, reason
    except json.JSONDecodeError:
        logger.error(f"Failed to parse AI response: {raw_text}")
        return 0, False, "Could not process your screenshot. Please send a clear screenshot."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_name = update.effective_user.first_name or "there"
    counter = load_counter()

    keyboard = [[InlineKeyboardButton("📤 Share Folder Link", url=f"https://t.me/share/url?url={FOLDER_LINK}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"💎 VIP ACCESS VERIFICATION 💎\n\n"
        f"👥 {counter} members have joined so far!\n\n"
        f"Welcome {user_name}! You are one step away from exclusive access...\n\n"
        f"To unlock your personal invite link:\n\n"
        f"1️⃣ Tap the button below and share the folder link to 3 different Telegram channels or groups\n\n"
        f"2️⃣ Screenshot your shares\n"
        f"3️⃣ Send the screenshot here for verification\n\n"
        f"⚡ Our AI verifies instantly!",
        reply_markup=reply_markup
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "there"
    username = f"@{update.effective_user.username}" if update.effective_user.username else "no username"

    used_users = load_used_users()
    if user_id in used_users:
        await update.message.reply_text(
            f"⚠️ {user_name}, you have already received your VIP invite link!\n"
            f"Each user can only receive it once. 💎"
        )
        return

    processing_msg = await update.message.reply_text(
        "🔍 Verifying your screenshot... please wait."
    )

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        count, is_valid, reason = await verify_screenshot_with_ai(bytes(image_bytes))

        if is_valid:
            invite = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                name=f"VIP {user_name}"
            )
            used_users.add(user_id)
            save_used_users(used_users)
            counter = load_counter() + 1
            save_counter(counter)

            await processing_msg.edit_text(
                f"✅ VERIFIED — VIP ACCESS GRANTED\n\n"
                f"Congratulations {user_name}! Here is your personal invite link:\n\n"
                f"🔗 {invite.invite_link}\n\n"
                f"This link is yours only and expires after 1 use.\n"
                f"Welcome to the VIP! 💎"
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"✅ VERIFIED\n\n"
                     f"👤 {user_name} ({username})\n"
                     f"🆔 {user_id}\n"
                     f"📊 Shared to: {count} channels\n"
                     f"🔗 Invite sent: {invite.invite_link}\n"
                     f"👥 Total joined: {load_counter()}"
            )

        elif count == 2:
            await processing_msg.edit_text(
                f"⚠️ So close {user_name}!\n\n"
                f"You only shared to 2 channels, share 1 more time to get access!"
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ FAILED — 2 CHANNELS\n\n"
                     f"👤 {user_name} ({username})\n"
                     f"🆔 {user_id}\n"
                     f"📊 Only shared to 2 channels"
            )

        elif count == 1:
            await processing_msg.edit_text(
                f"⚠️ Not quite {user_name}!\n\n"
                f"You only shared to 1 channel, share 2 more times to get access!"
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ FAILED — 1 CHANNEL\n\n"
                     f"👤 {user_name} ({username})\n"
                     f"🆔 {user_id}\n"
                     f"📊 Only shared to 1 channel"
            )

        else:
            await processing_msg.edit_text(
                f"❌ Struggling to share the link {user_name}?\n\n"
                f"Please contact Reggie for help!"
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ FAILED — INVALID SCREENSHOT\n\n"
                     f"👤 {user_name} ({username})\n"
                     f"🆔 {user_id}\n"
                     f"📊 No valid shares detected"
            )

    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}")
        await processing_msg.edit_text(
            "⚠️ Something went wrong. Please try again."
        )

async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"📸 Hey {user_name}, please send a screenshot as proof of your shares.\n\n"
        f"Type /start for instructions."
    )

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(~filters.PHOTO & ~filters.COMMAND, handle_non_photo))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
