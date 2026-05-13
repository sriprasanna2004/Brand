import asyncio
import os
from datetime import datetime, timezone, date

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.models import Lead, LeadStatus, Post, PostStatus, WhatsappSequence, SequenceStatus, AdaptiqTrial


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_sync_session():
    db_url = os.getenv("DATABASE_URL_SYNC", "")
    if not db_url:
        db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


def _run_async(coro):
    """Run an async coroutine safely from a sync APScheduler job."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _today_start() -> datetime:
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
    from src.scheduler.tasks import run_publish_pending_task
    logger.info("[Cron] Triggering publish pending posts")
    run_publish_pending_task.delay()


def _trigger_community_broadcast():
    """8 AM — run content crew and broadcast caption_a to Telegram community."""
    async def _run():
        from src.crews.content_crew import run_content_crew
        from src.tools.telegram_tool import broadcast_to_community
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
    today = _today_start()
    db = _get_sync_session()
    try:
        posts_today = db.execute(
            select(func.count(Post.id)).where(
                Post.posted_at >= today,
                Post.status == PostStatus.posted,
            )
        ).scalar() or 0

        leads_today = db.execute(
            select(func.count(Lead.id)).where(Lead.created_at >= today)
        ).scalar() or 0

        whatsapp_sent = db.execute(
            select(func.count(WhatsappSequence.id)).where(
                WhatsappSequence.sent_at >= today,
                WhatsappSequence.status == SequenceStatus.sent,
            )
        ).scalar() or 0

        trials_started = db.execute(
            select(func.count(AdaptiqTrial.id)).where(AdaptiqTrial.trial_start >= today)
        ).scalar() or 0

    except Exception as e:
        logger.error(f"[Cron] Daily summary DB query failed: {e}")
        posts_today = leads_today = whatsapp_sent = trials_started = 0
    finally:
        db.close()

    async def _send():
        from src.tools.telegram_tool import send_daily_summary
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

    _run_async(_send())


def _trigger_trial_sequences():
    """11:30 AM — send Adaptiq promo messages to active trial users."""
    from src.tools.adaptiq_tool import run_trial_sequences
    _run_async(run_trial_sequences())


def _trigger_nurture_sequences():
    """
    10 AM daily — fallback sweep for leads that missed their Celery ETA task.
    Primary nurture path is event-driven via Celery ETA in LeadCrew.
    This cron is a safety net only.
    """
    from src.scheduler.tasks import run_nurture_scheduled_task

    db = _get_sync_session()
    try:
        leads = db.execute(
            select(Lead).where(
                Lead.status != LeadStatus.opted_out,
                Lead.phone.isnot(None),
                Lead.nurture_enrolled_at.isnot(None),
            )
        ).scalars().all()
    except Exception as e:
        logger.error(f"[Cron] Nurture query failed: {e}")
        leads = []
    finally:
        db.close()

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


def _trigger_insights_sync():
    """10 PM — sync Instagram insights for posted posts. Now sync, no event loop needed."""
    from src.tools.analytics_tool import sync_post_analytics
    try:
        updated = sync_post_analytics()
        logger.info(f"[Cron] Insights sync complete — {updated} posts updated")
    except Exception as e:
        logger.error(f"[Cron] Insights sync failed: {e}")


def _trigger_trial_story():
    """Sunday 9 AM — post Adaptiq trial promo story to Instagram."""
    from src.scheduler.tasks import run_trial_story_task
    logger.info("[Cron] Triggering Adaptiq trial story")
    run_trial_story_task.delay()


def _trigger_daily_landing_promo():
    """12 PM daily — share Adaptiq landing page on Telegram + WhatsApp."""
    from src.scheduler.tasks import run_daily_landing_promo_task
    logger.info("[Cron] Triggering daily landing page promo")
    run_daily_landing_promo_task.delay()


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    scheduler.add_job(
        _trigger_content_crew,
        trigger="cron",
        day_of_week="sun",
        hour=6, minute=0,
        id="weekly_content_plan",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_content_crew,
        trigger="cron",
        hour=6, minute=0,
        id="daily_content_post",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_community_broadcast,
        trigger="cron",
        hour=8, minute=0,
        id="daily_community_broadcast",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_nurture_sequences,
        trigger="cron",
        hour=10, minute=0,
        id="daily_nurture",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_trial_sequences,
        trigger="cron",
        hour=11, minute=30,
        id="daily_adaptiq_trials",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_publish_pending,
        trigger="cron",
        hour=19, minute=30,
        id="daily_publish",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_daily_summary,
        trigger="cron",
        hour=21, minute=0,
        id="daily_summary",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_analytics_crew,
        trigger="cron",
        hour=23, minute=0,
        id="daily_analytics",
        replace_existing=True,
    )

    scheduler.add_job(
        _trigger_insights_sync,
        trigger="cron",
        hour=22, minute=0,
        id="daily_insights_sync",
        replace_existing=True,
    )

    # Weekly Adaptiq trial story — every Sunday at 9:00 AM IST
    scheduler.add_job(
        _trigger_trial_story,
        trigger="cron",
        day_of_week="sun",
        hour=9, minute=0,
        id="weekly_trial_story",
        replace_existing=True,
    )

    # Daily landing page promo — every day at 12:00 PM IST
    scheduler.add_job(
        _trigger_daily_landing_promo,
        trigger="cron",
        hour=12, minute=0,
        id="daily_landing_promo",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] APScheduler started with 11 cron jobs")
    return scheduler
