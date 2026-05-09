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
    backend=REDIS_URL_BROKER,
    include=["src.scheduler.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
)


def run_async(coro):
    """
    Run an async coroutine safely from a Celery worker context.
    Uses a ThreadPoolExecutor to avoid event loop conflicts when
    Celery workers already have a running loop.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
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
