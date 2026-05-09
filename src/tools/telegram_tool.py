import os

from loguru import logger
from telegram import Bot
from telegram.error import TelegramError


def _bot() -> Bot:
    return Bot(token=os.getenv("TELEGRAM_BOT_TOKEN", ""))


def _admin_chat() -> str:
    return os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")


async def send_admin_alert(message: str) -> bool:
    try:
        async with _bot() as bot:
            await bot.send_message(chat_id=_admin_chat(), text=message)
        logger.info(f"[Telegram] Admin alert sent: {message[:60]}...")
        return True
    except TelegramError as e:
        logger.error(f"[Telegram] send_admin_alert failed: {e}")
        return False


async def send_hot_lead_alert(ig_handle: str, keywords: list[str], auto_reply: str) -> bool:
    message = (
        f"🔥 HOT LEAD DETECTED\n"
        f"Instagram: @{ig_handle}\n"
        f"Keywords: {', '.join(keywords)}\n"
        f"Auto-reply sent: {auto_reply}\n"
        f"Action: Check DMs now"
    )
    return await send_admin_alert(message)


async def send_daily_summary(
    posts_today: int,
    leads_today: int,
    whatsapp_sent: int,
    trials_started: int,
) -> bool:
    message = (
        f"📊 BrandIQ Daily Summary\n"
        f"Posts published: {posts_today}\n"
        f"New leads: {leads_today}\n"
        f"WhatsApp messages sent: {whatsapp_sent}\n"
        f"Adaptiq trials started: {trials_started}"
    )
    return await send_admin_alert(message)


async def send_failure_alert(agent_name: str, error: str, job_id: str) -> bool:
    message = (
        f"❌ Agent Failure\n"
        f"Agent: {agent_name}\n"
        f"Job ID: {job_id}\n"
        f"Error: {error[:200]}"
    )
    return await send_admin_alert(message)


async def broadcast_to_community(message: str, chat_id: str) -> bool:
    try:
        async with _bot() as bot:
            await bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"[Telegram] Broadcast sent to chat_id={chat_id}")
        return True
    except TelegramError as e:
        logger.error(f"[Telegram] broadcast failed to {chat_id}: {e}")
        return False
