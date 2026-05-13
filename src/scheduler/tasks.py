import asyncio
import concurrent.futures
import os
from datetime import date, datetime, timezone, timedelta

import sentry_sdk
from celery import Celery
from loguru import logger

import re as _re

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_URL_BROKER = _re.sub(r'ssl_cert_reqs=CERT_NONE', 'ssl_cert_reqs=none', REDIS_URL, flags=_re.IGNORECASE)

celery_app = Celery(
    "brandiq",
    broker=REDIS_URL_BROKER,
    include=["src.scheduler.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    # Reduce Redis usage significantly
    task_ignore_result=True,
    result_backend=None,
    worker_prefetch_multiplier=1,
    broker_heartbeat=60,
    broker_connection_retry_on_startup=True,
    beat_max_loop_interval=300,
    worker_send_task_events=False,
    task_send_sent_event=False,
)


def run_async(coro):
    """
    Run an async coroutine safely from a Celery worker context.
    Uses a ThreadPoolExecutor to avoid event loop conflicts.
    Disposes the SQLAlchemy engine before each run to prevent
    asyncpg connection pool conflicts across event loops.
    """
    async def _wrapped():
        # Import here to avoid circular imports
        from src.database import engine
        # Dispose existing connections — they belong to a different event loop
        await engine.dispose()
        return await coro

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _wrapped())
        return future.result()


def _send_telegram_alert(message: str) -> None:
    """Fire-and-forget Telegram alert to admin (sync wrapper for Celery context)."""
    try:
        import httpx
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
        if not token or not chat_id:
            return
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram alert failed: {e}")


# ---------------------------------------------------------------------------
# Task 1: Content crew
# ---------------------------------------------------------------------------

@celery_app.task(
    name="content.weekly",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def run_content_crew_task(self):
    from src.crews.content_crew import run_content_crew
    try:
        result = run_async(run_content_crew(week_start=date.today()))
        logger.info("Content crew completed successfully")
        return result
    except Exception as exc:
        logger.error(f"[content.weekly] Attempt {self.request.retries + 1} failed: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            msg = f"[BrandIQ] Content crew failed after 3 retries: {exc}"
            logger.error(msg)
            sentry_sdk.capture_exception(exc)
            _send_telegram_alert(msg)
            try:
                from src.tools.telegram_tool import send_failure_alert
                run_async(send_failure_alert(
                    agent_name="ContentCrew",
                    error=str(exc),
                    job_id=f"content_{date.today()}",
                ))
            except Exception:
                pass
            raise


# ---------------------------------------------------------------------------
# Task 2: Lead crew
# ---------------------------------------------------------------------------

@celery_app.task(
    name="lead.process",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def run_lead_crew_task(self, ig_handle: str, message_text: str = "", day_number: int = 0):
    from src.crews.lead_crew import run_lead_crew
    try:
        result = run_async(run_lead_crew(
            ig_handle=ig_handle,
            message_text=message_text,
            day_number=day_number,
        ))
        return result
    except Exception as exc:
        logger.error(f"[lead.process] @{ig_handle} day={day_number} failed: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            sentry_sdk.capture_exception(exc)
            try:
                from src.tools.telegram_tool import send_failure_alert
                run_async(send_failure_alert(
                    agent_name="LeadCrew",
                    error=str(exc),
                    job_id=f"lead_{ig_handle}_{day_number}",
                ))
            except Exception:
                pass
            raise


# ---------------------------------------------------------------------------
# Task 3: Analytics crew
# ---------------------------------------------------------------------------

@celery_app.task(
    name="analytics.daily",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def run_analytics_crew_task(self):
    from src.crews.analytics_crew import run_analytics_crew
    try:
        result = run_async(run_analytics_crew())
        return result
    except Exception as exc:
        logger.error(f"[analytics.daily] Failed: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            sentry_sdk.capture_exception(exc)
            try:
                from src.tools.telegram_tool import send_failure_alert
                run_async(send_failure_alert(
                    agent_name="AnalyticsCrew",
                    error=str(exc),
                    job_id=f"analytics_{date.today()}",
                ))
            except Exception:
                pass
            raise


# ---------------------------------------------------------------------------
# Task 4: Instant Instagram auto-reply after lead capture
# ---------------------------------------------------------------------------

@celery_app.task(
    name="lead.instant_reply",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def send_instant_ig_reply_task(self, ig_user_id: str, message: str):
    """Send an instant Instagram DM reply to a lead right after scoring."""
    from src.tools.instagram_tool import send_dm
    try:
        result = run_async(send_dm(ig_user_id=ig_user_id, message=message))
        if result:
            logger.info(f"[lead.instant_reply] Auto-reply sent to @{ig_user_id}")
        else:
            logger.warning(f"[lead.instant_reply] send_dm returned False for @{ig_user_id}")
        return {"sent": result, "ig_user_id": ig_user_id}
    except Exception as exc:
        logger.error(f"[lead.instant_reply] Failed for @{ig_user_id}: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            sentry_sdk.capture_exception(exc)
            raise


# ---------------------------------------------------------------------------
# Task 5: Scheduled WhatsApp nurture (Day 3 / 7 / 14)
# ---------------------------------------------------------------------------

@celery_app.task(
    name="lead.nurture_scheduled",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def run_nurture_scheduled_task(self, ig_handle: str, day_number: int):
    """
    Send a WhatsApp nurture message for a specific day.
    Called via Celery ETA scheduling — fires automatically at Day 3, 7, 14
    after the lead was first captured.
    """
    from src.crews.lead_crew import run_lead_crew
    try:
        result = run_async(run_lead_crew(
            ig_handle=ig_handle,
            message_text="",
            day_number=day_number,
        ))
        logger.info(f"[lead.nurture_scheduled] Day {day_number} sent for @{ig_handle}")
        return result
    except Exception as exc:
        logger.error(f"[lead.nurture_scheduled] Day {day_number} @{ig_handle} failed: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            sentry_sdk.capture_exception(exc)
            try:
                from src.tools.telegram_tool import send_failure_alert
                run_async(send_failure_alert(
                    agent_name="LeadNurture",
                    error=str(exc),
                    job_id=f"nurture_{ig_handle}_day{day_number}",
                ))
            except Exception:
                pass
            raise


def schedule_nurture_sequence(ig_handle: str, enrolled_at: datetime) -> None:
    """
    Enqueue Day 3, 7, and 14 nurture tasks with Celery ETA.
    Call this once when a lead is first captured (Day 0).
    """
    schedule = {
        3:  enrolled_at + timedelta(days=3),
        7:  enrolled_at + timedelta(days=7),
        14: enrolled_at + timedelta(days=14),
    }
    for day, eta in schedule.items():
        run_nurture_scheduled_task.apply_async(
            kwargs={"ig_handle": ig_handle, "day_number": day},
            eta=eta,
        )
        logger.info(
            f"[schedule_nurture_sequence] Day {day} queued for @{ig_handle} "
            f"at {eta.isoformat()}"
        )


# ---------------------------------------------------------------------------
# Task 6: Weekly Adaptiq trial story promo
# ---------------------------------------------------------------------------

@celery_app.task(
    name="story.trial_promo",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def run_trial_story_task(self):
    """Generate and post an Adaptiq trial promo story to Instagram."""
    from src.tools.instagram_tool import create_and_post_trial_story
    try:
        story_id = run_async(create_and_post_trial_story())
        if story_id:
            logger.info(f"[story.trial_promo] Story posted: {story_id}")
        else:
            logger.warning("[story.trial_promo] Story post returned None")
        return {"story_id": story_id}
    except Exception as exc:
        logger.error(f"[story.trial_promo] Failed: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            sentry_sdk.capture_exception(exc)
            raise


# ---------------------------------------------------------------------------
# Task 7: Daily Adaptiq landing page promo
# Shares the trial signup link on Telegram community + WhatsApp broadcast
# ---------------------------------------------------------------------------

@celery_app.task(
    name="promo.daily_landing",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def run_daily_landing_promo_task(self):
    """
    Post the Adaptiq landing page link daily across:
    - Telegram community channel
    - WhatsApp broadcast (to all leads with phone numbers)
    """
    import os

    LANDING_URL = os.getenv(
        "ADAPTIQ_LANDING_URL",
        "https://hospitable-comfort-production.up.railway.app/adaptiq"
    )

    PROMO_MESSAGES = [
        (
            f"🎯 Want to crack UPSC faster?\n\n"
            f"Try Adaptiq FREE for 7 days — AI that finds your weak areas and builds a personalised study plan.\n\n"
            f"👉 Start here: {LANDING_URL}\n\n"
            f"#UPSC #IAS #TopperIAS #Adaptiq"
        ),
        (
            f"📚 UPSC aspirants — this is for you.\n\n"
            f"Adaptiq analyses your weak subjects and gives you a day-by-day plan to fix them.\n"
            f"7-day free trial. No credit card.\n\n"
            f"👉 {LANDING_URL}\n\n"
            f"#UPSCPreparation #IASAspirant #TopperIAS"
        ),
        (
            f"💡 Did you know?\n\n"
            f"Students who use Adaptiq improve their mock scores by 22% in the first week.\n\n"
            f"Try it free for 7 days 👇\n"
            f"{LANDING_URL}\n\n"
            f"#UPSC #CivilServices #Adaptiq #TopperIAS"
        ),
        (
            f"🚀 Free 7-day UPSC prep trial — limited time.\n\n"
            f"Adaptiq by TOPPER IAS:\n"
            f"✅ Personalised study plan\n"
            f"✅ Weak area analysis\n"
            f"✅ Daily practice tests\n\n"
            f"Sign up free: {LANDING_URL}\n\n"
            f"#IAS #UPSC #TopperIAS"
        ),
        (
            f"⏰ Your UPSC preparation starts today.\n\n"
            f"Adaptiq gives you a personalised AI study plan based on your weak areas.\n"
            f"First 7 days completely free.\n\n"
            f"👉 {LANDING_URL}\n\n"
            f"#UPSC #IASPreparation #Adaptiq"
        ),
        (
            f"🏆 Priya Sharma cracked UPSC in her first attempt.\n\n"
            f"She used Adaptiq to identify her weak areas in Polity and Economy.\n"
            f"You can too — try it free for 7 days.\n\n"
            f"👉 {LANDING_URL}\n\n"
            f"#UPSCTopper #IAS #TopperIAS #Adaptiq"
        ),
        (
            f"📊 Your UPSC score depends on fixing your weak areas.\n\n"
            f"Adaptiq finds them in 20 minutes and builds your study plan.\n"
            f"Free for 7 days — no commitment.\n\n"
            f"Start now: {LANDING_URL}\n\n"
            f"#UPSC #IAS #StudyPlan #TopperIAS"
        ),
    ]

    # Rotate message based on day of week (0=Mon, 6=Sun)
    from datetime import date
    day_index = date.today().weekday()
    message = PROMO_MESSAGES[day_index % len(PROMO_MESSAGES)]

    results = {}

    # ── 1. Telegram community broadcast ──────────────────────────────────────
    async def _telegram():
        from src.tools.telegram_tool import broadcast_to_community
        community_chat_id = os.getenv("TELEGRAM_COMMUNITY_CHAT_ID", "")
        if not community_chat_id:
            logger.warning("[DailyPromo] TELEGRAM_COMMUNITY_CHAT_ID not set, skipping")
            return False
        return await broadcast_to_community(message, community_chat_id)

    try:
        tg_ok = run_async(_telegram())
        results["telegram"] = "sent" if tg_ok else "failed"
        logger.info(f"[DailyPromo] Telegram: {results['telegram']}")
    except Exception as e:
        results["telegram"] = f"error: {e}"
        logger.error(f"[DailyPromo] Telegram failed: {e}")

    # ── 2. WhatsApp to all leads with phone numbers ───────────────────────────
    async def _whatsapp():
        from sqlalchemy import create_engine, select as sa_select
        from sqlalchemy.orm import sessionmaker
        from src.models import Lead, LeadStatus
        from src.tools.whatsapp_tool import send_text_message

        db_url = os.getenv("DATABASE_URL_SYNC", "").replace("postgresql+asyncpg://", "postgresql://") \
                 or os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(db_url, pool_pre_ping=True)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            leads = db.execute(
                sa_select(Lead).where(
                    Lead.phone.isnot(None),
                    Lead.status != LeadStatus.opted_out,
                )
            ).scalars().all()
        finally:
            db.close()

        sent = 0
        # WhatsApp message — shorter, more personal
        wa_message = (
            f"Hi! 👋 TOPPER IAS here.\n\n"
            f"Try Adaptiq FREE for 7 days — AI-powered UPSC prep that finds your weak areas.\n\n"
            f"👉 {LANDING_URL}"
        )
        for lead in leads[:50]:  # cap at 50 per day to avoid spam flags
            try:
                ok = await send_text_message(phone=lead.phone, message=wa_message)
                if ok:
                    sent += 1
            except Exception:
                pass
        return sent

    try:
        wa_sent = run_async(_whatsapp())
        results["whatsapp"] = f"{wa_sent} sent"
        logger.info(f"[DailyPromo] WhatsApp: {wa_sent} messages sent")
    except Exception as e:
        results["whatsapp"] = f"error: {e}"
        logger.error(f"[DailyPromo] WhatsApp failed: {e}")

    logger.info(f"[DailyPromo] Daily landing promo complete: {results}")
    return results
