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


async def send_direct_message(chat_id: str, message: str) -> bool:
    """Send a direct Telegram message to a specific lead by their chat_id."""
    try:
        async with _bot() as bot:
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
            )
        logger.info(f"[Telegram] Direct message sent to chat_id={chat_id}")
        return True
    except TelegramError as e:
        logger.error(f"[Telegram] send_direct_message failed for chat_id={chat_id}: {e}")
        return False


async def handle_telegram_message(update: dict) -> dict:
    """
    Handle incoming Telegram bot messages.
    When a lead messages the bot, capture their chat_id and link to their lead record.
    Also trigger lead scoring if message contains intent keywords.
    """
    from src.scheduler.tasks import run_lead_crew_task

    try:
        message = update.get("message", {})
        if not message:
            return {"status": "ignored", "reason": "no_message"}

        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        from_user = message.get("from", {})
        username = from_user.get("username", "")
        first_name = from_user.get("first_name", "")
        full_name = f"{first_name} {from_user.get('last_name', '')}".strip()

        if not chat_id:
            return {"status": "ignored", "reason": "no_chat_id"}

        logger.info(f"[Telegram] Message from chat_id={chat_id} @{username}: {text[:80]}")

        # Save/update lead with telegram_chat_id
        import os
        from sqlalchemy import create_engine, select as sa_select
        from sqlalchemy.orm import sessionmaker
        from src.models import Lead, LeadSource, LeadStatus
        import uuid as _uuid

        db_url = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(db_url, pool_pre_ping=True)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            # Try to find existing lead by telegram chat_id or username
            lead = None
            if username:
                lead = db.execute(
                    sa_select(Lead).where(Lead.ig_handle == f"tg_{username}")
                ).scalar_one_or_none()

            if not lead:
                # Create new lead from Telegram
                ig_handle = f"tg_{username}" if username else f"tg_{chat_id}"
                lead = Lead(
                    id=_uuid.uuid4(),
                    ig_handle=ig_handle,
                    name=full_name or username or None,
                    status=LeadStatus.warm,
                    source=LeadSource.telegram,
                    telegram_chat_id=chat_id,
                )
                db.add(lead)
            else:
                # Update chat_id if missing
                if not lead.telegram_chat_id:
                    lead.telegram_chat_id = chat_id
                if full_name and not lead.name:
                    lead.name = full_name

            db.commit()
            ig_handle = lead.ig_handle
        finally:
            db.close()

        # Dispatch lead scoring task (same flow as Instagram DM)
        run_lead_crew_task.delay(
            ig_handle=ig_handle,
            message_text=text,
            day_number=0,
        )

        logger.info(f"[Telegram] Lead task queued for {ig_handle}")
        return {"status": "processed", "chat_id": chat_id, "ig_handle": ig_handle}

    except Exception as e:
        logger.error(f"[Telegram] handle_telegram_message failed: {e}")
        return {"status": "error", "detail": str(e)}
