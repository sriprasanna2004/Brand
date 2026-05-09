import asyncio
import os
from datetime import datetime, timezone, date

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger
from sqlalchemy import select, func

from src.database import AsyncSessionLocal
from src.models import Lead, LeadStatus, Post, PostStatus, WhatsappSequence, SequenceStatus, AdaptiqTrial


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine safely from a sync APScheduler job."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)
    d = date.today()
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------

def _trigger_content_crew():
    from src.scheduler.tasks import run_content_crew_task
    logger.info("[Cron] Triggering content crew")
    run_content_crew_task.delay()


def _trigger_analytics_crew():
    from src.scheduler.tasks import run_analytics_crew_task
    logger.info("[Cron] Triggering analytics crew")
    run_analytics_crew_task.delay()


def _trigger_publish_pending():
    from src.tools.post_publisher import publish_pending_posts
    logger.info("[Cron] Publishing pending posts")
    asyncio.run(publish_pending_posts())


def _trigger_community_broadcast():
    """8 AM — run content crew and broadcast caption_a to Telegram community."""
    from src.scheduler.tasks import run_content_crew_task
    from src.tools.telegram_tool import broadcast_to_community

    async def _run():
        from src.crews.content_crew import run_content_crew
        community_chat_id = os.getenv("TELEGRAM_COMMUNITY_CHAT_ID", "")
        if not community_chat_id:
            logger.warning("[Cron] TELEGRAM_COMMUNITY_CHAT_ID not set, skipping broadcast")
            return
        try:
            result = await run_content_crew(week_start=date.today())
            caption = result.get("caption_a", "")
            if caption:
                await broadcast_to_community(caption, community_chat_id)
                logger.info("[Cron] Community broadcast sent")
        except Exception as e:
            logger.error(f"[Cron] Community broadcast failed: {e}")

    _run_async(_run())


def _trigger_daily_summary():
    """9 PM — query DB stats and send Telegram daily summary."""
    from src.tools.telegram_tool import send_daily_summary

    async def _run():
        today = _today_start()
        async with AsyncSessionLocal() as db:
            posts_today = await db.scalar(
                select(func.count(Post.id)).where(
                    Post.posted_at >= today,
                    Post.status == PostStatus.posted,
                )
            ) or 0

            leads_today = await db.scalar(
                select(func.count(Lead.id)).where(Lead.created_at >= today)
            ) or 0

            whatsapp_sent = await db.scalar(
                select(func.count(WhatsappSequence.id)).where(
                    WhatsappSequence.sent_at >= today,
                    WhatsappSequence.status == SequenceStatus.sent,
                )
            ) or 0

            trials_started = await db.scalar(
                select(func.count(AdaptiqTrial.id)).where(AdaptiqTrial.trial_start >= today)
            ) or 0

        await send_daily_summary(
            posts_today=posts_today,
            leads_today=leads_today,
            whatsapp_sent=whatsapp_sent,
            trials_started=trials_started,
        )
        logger.info(
            f"[Cron] Daily summary sent — posts={posts_today}, leads={leads_today}, "
            f"wa={whatsapp_sent}, trials={trials_started}"
        )

    _run_async(_run())


def _trigger_trial_sequences():
    """11:30 AM — send Adaptiq promo messages to active trial users."""
    from src.tools.adaptiq_tool import run_trial_sequences

    async def _run():
        count = await run_trial_sequences()
        logger.info(f"[Cron] Adaptiq trial sequences sent: {count}")

    _run_async(_run())


def _trigger_nurture_sequences():
    """
    10 AM daily — fallback sweep for leads that missed their Celery ETA task
    (e.g. worker was down, lead has no phone yet but now does).

    The primary nurture path is event-driven: Day 3/7/14 tasks are scheduled
    via Celery ETA inside LeadCrew when a lead is first captured (Day 0).
    This cron is a safety net only.
    """
    from src.scheduler.tasks import run_nurture_scheduled_task

    async def _query():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Lead).where(
                    Lead.status != LeadStatus.opted_out,
                    Lead.phone.isnot(None),
                    Lead.nurture_enrolled_at.isnot(None),
                )
            )
            return result.scalars().all()

    leads = _run_async(_query())
    now = datetime.now(timezone.utc)

    for lead in leads:
        days_since_enrolled = (now - lead.nurture_enrolled_at).days
        if days_since_enrolled in (3, 7, 14):
            logger.info(
                f"[Cron] Fallback nurture day={days_since_enrolled} for @{lead.ig_handle}"
            )
            run_nurture_scheduled_task.delay(
                ig_handle=lead.ig_handle,
                day_number=days_since_enrolled,
            )


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Weekly content plan — every Sunday at 6:00 AM
    scheduler.add_job(
        _trigger_content_crew,
        trigger="cron",
        day_of_week="sun",
        hour=6,
        minute=0,
        id="weekly_content_plan",
        replace_existing=True,
    )

    # Daily post generation — every day at 6:00 AM
    scheduler.add_job(
        _trigger_content_crew,
        trigger="cron",
        hour=6,
        minute=0,
        id="daily_content_post",
        replace_existing=True,
    )

    # Community broadcast — every day at 8:00 AM
    scheduler.add_job(
        _trigger_community_broadcast,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_community_broadcast",
        replace_existing=True,
    )

    # Nurture sequences — every day at 10:00 AM
    scheduler.add_job(
        _trigger_nurture_sequences,
        trigger="cron",
        hour=10,
        minute=0,
        id="daily_nurture",
        replace_existing=True,
    )

    # Adaptiq trial sequences — every day at 11:30 AM
    scheduler.add_job(
        _trigger_trial_sequences,
        trigger="cron",
        hour=11,
        minute=30,
        id="daily_adaptiq_trials",
        replace_existing=True,
    )

    # Publish pending posts — every day at 7:30 PM
    scheduler.add_job(
        _trigger_publish_pending,
        trigger="cron",
        hour=19,
        minute=30,
        id="daily_publish",
        replace_existing=True,
    )

    # Daily summary — every day at 9:00 PM
    scheduler.add_job(
        _trigger_daily_summary,
        trigger="cron",
        hour=21,
        minute=0,
        id="daily_summary",
        replace_existing=True,
    )

    # Analytics — every day at 11:00 PM
    scheduler.add_job(
        _trigger_analytics_crew,
        trigger="cron",
        hour=23,
        minute=0,
        id="daily_analytics",
        replace_existing=True,
    )

    # Sync Instagram Insights — every day at 10:00 PM
    scheduler.add_job(
        lambda: _run_async(__import__('src.tools.analytics_tool', fromlist=['sync_post_analytics']).sync_post_analytics()),
        trigger="cron",
        hour=22,
        minute=0,
        id="daily_insights_sync",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] APScheduler started with 8 cron jobs")
    return scheduler


