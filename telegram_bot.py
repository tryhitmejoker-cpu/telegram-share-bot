#!/usr/bin/env python3
"""
Telegram Share-Proof Bot
- User sends a screenshot proving they shared the main channel post to 5 channels
- AI (Claude) verifies the screenshot
- If valid and user hasn't received the link before → send invite link
- If invalid → send rejection message
"""

import logging
import base64
import json
import os
import httpx
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
INVITE_LINK        = os.environ["INVITE_LINK"]
MAIN_CHANNEL       = os.environ["MAIN_CHANNEL"]

USED_USERS_FILE = "used_users.json"

# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# PERSISTENCE HELPERS
# ─────────────────────────────────────────
def load_used_users() -> set:
    if Path(USED_USERS_FILE).exists():
        with open(USED_USERS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_used_users(users: set):
    with open(USED_USERS_FILE, "w") as f:
        json.dump(list(users), f)

# ─────────────────────────────────────────
# AI VERIFICATION VIA CLAUDE
# ─────────────────────────────────────────
async def verify_screenshot_with_ai(image_bytes: bytes) -> tuple[bool, str]:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = f"""You are a verification assistant for a Telegram bot.

A user claims to have shared a post from the Telegram channel '{MAIN_CHANNEL}' to 5 different Telegram channels or groups, and has sent a screenshot as proof.

Carefully examine the screenshot and determine:
1. Does it show a Telegram interface?
2. Does it show evidence of a post being shared or forwarded?
3. Does it look like a legitimate screenshot (not edited, blank, or unrelated)?

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{{"valid": true, "reason": "Brief reason"}}
or
{{"valid": false, "reason": "Brief reason explaining what's wrong"}}"""

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 200,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            },
        )

    if response.status_code != 200:
        logger.error(f"Anthropic API error: {response.text}")
        return False, "Verification service error. Please try again later."

    data = response.json()
    raw_text = data["content"][0]["text"].strip()

    try:
        result = json.loads(raw_text)
        return bool(result.get("valid", False)), result.get("reason", "No reason provided")
    except json.JSONDecodeError:
        logger.error(f"Failed to parse AI response: {raw_text}")
        return False, "Could not process your screenshot. Please send a clear screenshot."

# ─────────────────────────────────────────
# TELEGRAM HANDLERS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 Welcome!\n\n"
        f"To receive the exclusive invite link, follow these steps:\n\n"
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
        await update.message.reply_text(
            "⚠️ You've already received the invite link! Each user can only receive it once."
        )
        return

    processing_msg = await update.message.reply_text(
        "🔍 Verifying your screenshot with AI... please wait a moment."
    )

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        is_valid, reason = await verify_screenshot_with_ai(bytes(image_bytes))

        if is_valid:
            used_users.add(user_id)
            save_used_users(used_users)

            await processing_msg.edit_text(
                f"✅ *Verification successful!*\n\n"
                f"Thank you {user_name}! Here is your exclusive invite link:\n\n"
                f"🔗 {INVITE_LINK}\n\n"
                f"_This link is for you only — please don't share it._",
                parse_mode="Markdown"
            )
        else:
            await processing_msg.edit_text(
                f"❌ *Verification failed*\n\n"
                f"Reason: {reason}\n\n"
                f"Please make sure your screenshot clearly shows that you've shared a post "
                f"from {MAIN_CHANNEL} to 5 channels/groups, then try again.",
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"Error processing photo for user {user_id}: {e}")
        await processing_msg.edit_text(
            "⚠️ Something went wrong while processing your screenshot. Please try again."
        )

async def handle_non_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Please send a *photo/screenshot* as proof of your shares.\n\n"
        "Type /start for instructions.",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(~filters.PHOTO & ~filters.COMMAND, handle_non_photo))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

