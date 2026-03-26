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
INVITE_LINK        = os.environ["INVITE_LINK"]
MAIN_CHANNEL       = os.environ["MAIN_CHANNEL"]

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

async def verify_screenshot_with_ai(image_bytes: bytes) -> tuple[bool, str]:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = f"""You are a verification assistant for a Telegram bot.
A user claims to have shared a post from '{MAIN_CHANNEL}' to 5 different Telegram channels and sent a screenshot as proof.
Check: 1) Does it show Telegram? 2) Does it show a forwarded/shared post? 3) Is it a real screenshot?
Respond ONLY with JSON, no extra text:
{{"valid": true, "reason": "Brief reason"}} or {{"valid": false, "reason": "Brief reason"}}"""

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
        return False, "Verification service error. Please try again later."

    data = response.json()
    raw_text = data["choices"][0]["message"]["content"].strip()
    try:
        clean = raw_text.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        return bool(result.get("valid", False)), result.get("reason", "No reason provided")
    except json.JSONDecodeError:
        logger.error(f"Failed to parse AI response: {raw_text}")
        return False, "Could not process your screenshot. Please send a clear screenshot."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 Welcome!\n\nTo receive the exclusive invite link:\n\n"
        f"1️⃣ Go to {MAIN_CHANNEL}\n"
        f"2️⃣ Share any post to *5 different Telegram channels or groups*\n"
        f"3️⃣ Take a screenshot showing the shares\n"
        f"4️⃣ Send the screenshot here\n\n"
        f"Our AI will verify your proof and send you the invite link! ✅",
        parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name or "there"

    used_users = load_used_users()
    if user_id in used_users:
        await update.message.reply_text("⚠️ You've already received the invite link! Each user can only receive it once.")
        return

    processing_msg = await update.message.reply_text("🔍 Verifying your screenshot with AI... please wait.")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        is_valid, reason = await verify_screenshot_with_ai(bytes(image_bytes))

        if is_valid:
            used_users.add(user_id)
            save_used_users(used_users)
            await processing_msg.edit_text(
                f"✅ *Verification successful!*\n\nThank you {user_name}! Here is your exclusive invite link:\n\n"
                f"🔗 {INVITE_LINK}\n\n_This link is for you only — please don't share it._",
                parse_mode="Markdown"
            )
        else:
            await processing_msg.edit_text(
                f"❌ *Verification failed*\n\nReason: {reason}\n\n"
                f"Make sure your screenshot clearly shows you shared a post from {MAIN_CHANNEL} to 5 channels, then try again.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}")
        await processing_msg.edit_text("⚠️ Something went wrong. Please try again.")

async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Please send a *photo/screenshot* as proof.\n\nType /start for instructions.", parse_mode="Markdown")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(~filters.PHOTO & ~filters.COMMAND, handle_non_photo))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
