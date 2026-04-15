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
ADMIN_ID           = int(os.environ["ADMIN_ID"])
ADMIN_USER_ID      = 8633029909

USED_USERS_FILE    = "used_users.json"
COUNTER_FILE       = "counter.json"
SPACES_FILE        = "spaces.json"
SPACES_MAX         = 6

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

def load_spaces() -> int:
    if Path(SPACES_FILE).exists():
        with open(SPACES_FILE, "r") as f:
            return json.load(f).get("spaces", SPACES_MAX)
    return SPACES_MAX

def save_spaces(spaces: int):
    with open(SPACES_FILE, "w") as f:
        json.dump({"spaces": spaces}, f)

def decrement_spaces():
    spaces = load_spaces()
    spaces -= 1
    if spaces <= 0:
        spaces = SPACES_MAX
    save_spaces(spaces)
    return spaces

async def verify_screenshot_with_ai(image_bytes: bytes) -> tuple[int, bool, str]:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = """Look at this screenshot carefully.

You are verifying if someone has shared a Telegram link to 3 or more different chats.

Respond ONLY with JSON:
{"count": 3, "valid": true, "reason": "ok"}

Rules:
- Only valid if you can CLEARLY see 3 or more chats selected with blue ticks
- Only valid if Send (3) or higher is clearly visible
- If you see Send (2): count=2, valid=false
- If you see Send (1): count=1, valid=false
- If unclear or can't confirm 3 shares: valid=false
- If not Telegram at all: count=0, valid=false
- Do NOT default to valid=true if unsure — default to valid=false"""

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
    spaces = load_spaces()

    keyboard = [[InlineKeyboardButton("📤 Share & Unlock Access", url=f"https://t.me/share/url?url={FOLDER_LINK}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"👑 STRICKLY VIP 👑\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 Welcome {user_name}!\n\n"
        f"You've been selected for exclusive VIP access. "
        f"Join {counter} members already inside! 💎\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔐 HOW TO UNLOCK ACCESS\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"1️⃣ Tap the button below\n"
        f"2️⃣ Share the link to 3 different Telegram groups or channels\n"
        f"3️⃣ Send a screenshot as proof of your shares\n"
        f"4️⃣ Our AI will verify instantly ⚡\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆓 Free Channel — Strictly Baddies\n"
        f"⚠️ Only {spaces} spaces left — act fast!\n\n"
        f"🎁 Your FREE VIP link is one step away... 🚀",
        reply_markup=reply_markup
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast Your message here")
        return

    message = " ".join(context.args)
    used_users = load_used_users()
    success = 0
    failed = 0

    await update.message.reply_text(f"📢 Sending to {len(used_users)} users...")

    for user_id in used_users:
        try:
            await context.bot.send_message(chat_id=int(user_id), text=message)
            success += 1
        except Exception as e:
            logger.error(f"Failed to send to {user_id}: {e}")
            failed += 1

    await update.message.reply_text(
        f"✅ Broadcast complete!\n\nSent: {success}\nFailed: {failed}"
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

    if "attempts" not in context.user_data:
        context.user_data["attempts"] = 0

    processing_msg = await update.message.reply_text("🔍 Verifying your screenshot... please wait.")

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
            decrement_spaces()
            context.user_data["attempts"] = 0

            await processing_msg.edit_text(
                f"✅ VERIFIED — VIP ACCESS GRANTED\n\n"
                f"Congratulations {user_name}! Here is your personal invite link:\n\n"
                f"🔗 {invite.invite_link}\n\n"
                f"This link is yours only and expires after 1 use.\n"
                f"Welcome to the VIP! 💎"
            )

            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo.file_id,
                caption=f"✅ VERIFIED\n\n"
                        f"👤 {user_name} ({username})\n"
                        f"🆔 {user_id}\n"
                        f"📊 Shared to: {count} chats\n"
                        f"🔗 Invite sent: {invite.invite_link}\n"
                        f"👥 Total joined: {load_counter()}"
            )

        else:
            context.user_data["attempts"] += 1
            attempts = context.user_data["attempts"]

            if attempts >= 3:
                await processing_msg.edit_text(
                    f"❌ You have failed verification {attempts} times {user_name}.\n\n"
                    f"Please contact an admin for help: @stricklyvip"
                )
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"❌ FAILED 3+ TIMES\n\n👤 {user_name} ({username})\n🆔 {user_id}"
                )
            elif count == 2:
                await processing_msg.edit_text(
                    f"⚠️ So close {user_name}!\n\n"
                    f"You only shared to 2 chats — share 1 more and send a new screenshot!\n\n"
                    f"❌ Attempt {attempts}/3"
                )
            elif count == 1:
                await processing_msg.edit_text(
                    f"⚠️ Not quite {user_name}!\n\n"
                    f"You only shared to 1 chat — share 2 more and send a new screenshot!\n\n"
                    f"❌ Attempt {attempts}/3"
                )
            else:
                await processing_msg.edit_text(
                    f"❌ Screenshot not valid {user_name}.\n\n"
                    f"Please make sure you send a clear screenshot showing your shares.\n\n"
                    f"❌ Attempt {attempts}/3"
                )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ FAILED — ATTEMPT {attempts}\n\n👤 {user_name} ({username})\n🆔 {user_id}\n📊 Shares: {count}"
            )

    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}")
        await processing_msg.edit_text("⚠️ Something went wrong. Please try again.")

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
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(~filters.PHOTO & ~filters.COMMAND, handle_non_photo))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
