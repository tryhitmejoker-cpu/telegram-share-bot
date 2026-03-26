#!/usr/bin/env python3
import logging
import base64
import json
import os
import httpx
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
FOLDER_LINK        = os.environ["FOLDER_LINK"]
CHANNEL_ID         = int(os.environ["CHANNEL_ID"])

USED_USERS_FILE = "used_users.json"

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

async def verify_screenshot_with_ai(image_bytes: bytes) -> tuple[int, bool, str]:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = """You are a verification assistant for a Telegram bot.
A user claims to have shared a Telegram folder link to 3 different Telegram channels or groups and sent a screenshot as proof.

Carefully examine the screenshot and count how many different chats/channels/groups the link was shared to.

Respond ONLY with JSON, no extra text, in this exact format:
{"count": 3, "valid": true, "reason": "Brief reason"}

Rules:
- If it does not show Telegram at all or is not a real screenshot: count=0, valid=false
- If it shows the link shared to 1 chat: count=1, valid=false
- If it shows the link shared to 2 chats: count=2, valid=false
- If it shows the link shared to 3 or more chats: count=3, valid=true"""

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
    await update.message.reply_text(
        f"👋 Welcome!\n\n"
        f"To receive the exclusive invite link:\n\n"
        f"1️⃣ Share the folder link below to 3 different Telegram channels or groups:\n"
        f"{FOLDER_LINK}\n\n"
        f"2️⃣ Take a screenshot showing the shares\n"
        f"3️⃣ Send the screenshot here\n\n"
        f"Our AI will verify your proof and send you the invite link! ✅"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "there"

    used_users = load_used_users()
    if user_id in used_users:
        await update.message.reply_text(
            "⚠️ You have already received the invite link! Each user can only receive it once."
        )
        return

    processing_msg = await update.message.reply_text(
        "🔍 Verifying your screenshot with AI... please wait."
    )

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        count, is_valid, reason = await verify_screenshot_with_ai(bytes(image_bytes))

        if is_valid:
            # Generate a unique one-time invite link
            invite = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                name=f"User {user_id}"
            )
            used_users.add(user_id)
            save_used_users(used_users)
            await processing_msg.edit_text(
                f"✅ Verification successful!\n\n"
                f"Thank you {user_name}! Here is your exclusive invite link:\n\n"
                f"🔗 {invite.invite_link}\n\n"
                f"This link is for you only and can only be used once — please do not share it."
            )
        elif count == 2:
            await processing_msg.edit_text(
                "⚠️ You only shared to 2 channels, share 1 more time to get access!"
            )
        elif count == 1:
            await processing_msg.edit_text(
                "⚠️ You only shared to 1 channel, share 2 more times to get access!"
            )
        else:
            await processing_msg.edit_text(
                "❌ Struggling to share the link? Please contact Reggie!"
            )
    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}")
        await processing_msg.edit_text(
            "⚠️ Something went wrong. Please try again."
        )

async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Please send a photo/screenshot as proof.\n\nType /start for instructions."
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
