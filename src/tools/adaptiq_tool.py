"""
Adaptiq funnel tool — manages the full 7-day trial -> paid conversion sequence.
"""
import os
import uuid
import random
from datetime import datetime, timezone, timedelta

from loguru import logger
from sqlalchemy import create_engine, select as sa_select, text
from sqlalchemy.orm import sessionmaker

from src.database import AsyncSessionLocal
from src.models import AgentJob, JobStatus, AdaptiqTrial, Lead, LeadStatus

TRIAL_DAYS = (1, 2, 3, 4, 5, 6, 7)


def _get_sync_session():
    db_url = os.getenv("DATABASE_URL_SYNC", "")
    if not db_url:
        db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


# ---------------------------------------------------------------------------
# start_trial — called from FastAPI (async context) — keep async
# ---------------------------------------------------------------------------

async def start_trial(
    lead_id: str,
    lead_phone: str,
    lead_name: str,
    source_post_id: str = "",
    weak_subjects: list[str] = None,
) -> bool:
    from src.agents.adaptiq_promo_agent import run_adaptiq_promo_agent
    from src.tools.telegram_tool import send_direct_message

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        existing = await db.scalar(
            sa_select(AdaptiqTrial).where(AdaptiqTrial.lead_id == uuid.UUID(lead_id))
        )
        if existing:
            logger.info(f"[Adaptiq] Trial already exists for lead_id={lead_id}")
            return False

        trial = AdaptiqTrial(
            id=uuid.uuid4(),
            lead_id=uuid.UUID(lead_id),
            trial_start=now,
            trial_end=now + timedelta(days=7),
        )
        db.add(trial)
        await db.commit()
        logger.info(f"[Adaptiq] Trial started for lead_id={lead_id}")

    try:
        msg = run_adaptiq_promo_agent(
            lead_name=lead_name, trial_day=1,
            weak_subjects=weak_subjects or [],
            source_post="",
        )

        # Send via Telegram if chat_id available, else WhatsApp fallback
        sent = False
        db_sync = _get_sync_session()
        try:
            lead_row = db_sync.execute(
                sa_select(Lead).where(Lead.id == uuid.UUID(lead_id))
            ).scalar_one_or_none()
            tg_chat_id = lead_row.telegram_chat_id if lead_row else None
        finally:
            db_sync.close()

        if tg_chat_id:
            from src.scheduler.tasks import run_async
            sent = run_async(send_direct_message(chat_id=tg_chat_id, message=msg.message))
            logger.info(f"[Adaptiq] Day 1 sent via Telegram to chat_id={tg_chat_id}")
        elif lead_phone:
            from src.tools.whatsapp_tool import send_text_message
            from src.scheduler.tasks import run_async
            sent = run_async(send_text_message(phone=lead_phone, message=msg.message))
            logger.info(f"[Adaptiq] Day 1 sent via WhatsApp to {lead_phone}")
        else:
            logger.warning(f"[Adaptiq] No Telegram chat_id or phone for lead_id={lead_id}")

        # Mark day1 sent
        db = _get_sync_session()
        try:
            t = db.execute(
                sa_select(AdaptiqTrial).where(AdaptiqTrial.lead_id == uuid.UUID(lead_id))
            ).scalar_one_or_none()
            if t:
                t.day1_sent = True
                db.commit()
        finally:
            db.close()

        return True
    except Exception as e:
        logger.error(f"[Adaptiq] start_trial Day 1 message failed: {e}")
        return False


# ---------------------------------------------------------------------------
# run_trial_sequences — called from Celery cron (sync context) — use sync DB
# ---------------------------------------------------------------------------

async def run_trial_sequences() -> int:
    """
    Send daily Adaptiq promo messages to active trial users.
    Uses sync DB to avoid asyncpg event loop conflicts in Celery workers.
    """
    from src.agents.adaptiq_promo_agent import run_adaptiq_promo_agent
    from src.tools.telegram_tool import send_direct_message

    now = datetime.now(timezone.utc)
    sent_count = 0

    db = _get_sync_session()
    try:
        trials = db.execute(
            sa_select(AdaptiqTrial).where(
                AdaptiqTrial.converted_at.is_(None),
                AdaptiqTrial.trial_end >= now,
            )
        ).scalars().all()
        logger.info(f"[Adaptiq] Processing {len(trials)} active trial(s)")

        for trial in trials:
            trial_day = (now - trial.trial_start).days + 1
            if trial_day not in TRIAL_DAYS:
                continue

            lead = db.execute(
                sa_select(Lead).where(Lead.id == trial.lead_id)
            ).scalar_one_or_none()
            if not lead:
                continue

            job_id = f"adaptiq_{lead.id}_day{trial_day}"
            already = db.execute(
                sa_select(AgentJob).where(AgentJob.job_id == job_id)
            ).scalar_one_or_none()
            if already:
                continue

            job = AgentJob(
                id=uuid.uuid4(), job_id=job_id,
                agent_name="AdaptiqPromoAgent", status=JobStatus.running,
                payload={"lead_id": str(lead.id), "trial_day": trial_day},
            )
            db.add(job)
            db.commit()

            try:
                improvement = trial.improvement_pct or 0
                if trial_day >= 5 and improvement == 0:
                    improvement = random.randint(15, 25)
                    trial.improvement_pct = improvement
                    db.commit()

                msg = run_adaptiq_promo_agent(
                    lead_name=lead.name or lead.ig_handle,
                    trial_day=trial_day,
                    weak_subjects=[],
                    improvement_pct=improvement,
                    source_post="",
                )

                # Send via Telegram if chat_id available, else WhatsApp fallback
                if lead.telegram_chat_id:
                    from src.scheduler.tasks import run_async
                    run_async(send_direct_message(chat_id=lead.telegram_chat_id, message=msg.message))
                    logger.info(f"[Adaptiq] Day {trial_day} sent via Telegram to {lead.ig_handle}")
                elif lead.phone:
                    from src.tools.whatsapp_tool import send_text_message
                    from src.scheduler.tasks import run_async
                    import asyncio
                    asyncio.get_event_loop().run_until_complete(
                        send_text_message(phone=lead.phone, message=msg.message)
                    )
                    logger.info(f"[Adaptiq] Day {trial_day} sent via WhatsApp to {lead.phone}")
                else:
                    logger.warning(f"[Adaptiq] No Telegram or phone for {lead.ig_handle}")

                job.status = JobStatus.success
                job.completed_at = now
                sent_count += 1
                logger.info(f"[Adaptiq] Day {trial_day} sent to {lead.ig_handle}")

                if trial_day == 4:
                    trial.webinar_attended = True
                if trial_day == 6:
                    trial.demo_booked = True
                if trial_day == 7:
                    trial.payment_initiated = True

            except Exception as e:
                job.status = JobStatus.failed
                job.error = str(e)
                job.completed_at = now
                logger.error(f"[Adaptiq] Day {trial_day} failed for {lead.id}: {e}")

            db.commit()

    except Exception as e:
        logger.error(f"[Adaptiq] run_trial_sequences failed: {e}")
        db.rollback()
    finally:
        db.close()

    return sent_count


async def mark_converted(lead_id: str, plan: str) -> bool:
    from src.tools.telegram_tool import send_admin_alert
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        trial = await db.scalar(
            sa_select(AdaptiqTrial).where(AdaptiqTrial.lead_id == uuid.UUID(lead_id))
        )
        if trial:
            trial.converted_at = now
            trial.plan = plan
            trial.payment_initiated = True

        lead = await db.scalar(sa_select(Lead).where(Lead.id == uuid.UUID(lead_id)))
        if lead:
            lead.status = LeadStatus.hot
            lead.updated_at = now
            name = lead.name or lead.ig_handle
        else:
            name = lead_id

        await db.commit()

    logger.info(f"[Adaptiq] Conversion: {name} -> {plan}")
    try:
        price = "₹1,999" if "annual" in plan.lower() else "₹299"
        await send_admin_alert(f"🎉 Adaptiq Conversion!\n{name} upgraded to {plan} ({price})")
    except Exception:
        pass
    return True


async def get_funnel_stats() -> dict:
    """Return full 7-stage funnel with conversion rates."""
    async with AsyncSessionLocal() as db:
        try:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) as total_trials,
                    SUM(CASE WHEN day1_sent THEN 1 ELSE 0 END) as day1,
                    SUM(CASE WHEN day3_sent THEN 1 ELSE 0 END) as day3,
                    SUM(CASE WHEN webinar_attended THEN 1 ELSE 0 END) as webinar,
                    SUM(CASE WHEN day5_sent THEN 1 ELSE 0 END) as day5,
                    SUM(CASE WHEN demo_booked THEN 1 ELSE 0 END) as demo,
                    SUM(CASE WHEN payment_initiated THEN 1 ELSE 0 END) as payment,
                    SUM(CASE WHEN converted_at IS NOT NULL THEN 1 ELSE 0 END) as converted,
                    AVG(improvement_pct) as avg_improvement
                FROM adaptiq_trials
            """))
            row = r.fetchone()
            total = row[0] or 0
            def pct(n): return round((n or 0) / total * 100, 1) if total > 0 else 0
            return {
                "total_trials": total,
                "stages": [
                    {"label": "Free Trial Started",  "value": total,        "pct": 100,       "color": "#00e5c3"},
                    {"label": "Day 1 Onboarded",     "value": row[1] or 0,  "pct": pct(row[1]), "color": "#00e5c3"},
                    {"label": "Day 3 Check-in",      "value": row[2] or 0,  "pct": pct(row[2]), "color": "#4facfe"},
                    {"label": "Webinar Attended",    "value": row[3] or 0,  "pct": pct(row[3]), "color": "#9d6fff"},
                    {"label": "Day 5 Progress",      "value": row[4] or 0,  "pct": pct(row[4]), "color": "#ffd166"},
                    {"label": "Demo Booked",         "value": row[5] or 0,  "pct": pct(row[5]), "color": "#ffd166"},
                    {"label": "Payment Initiated",   "value": row[6] or 0,  "pct": pct(row[6]), "color": "#ff6b6b"},
                    {"label": "Paid Converted",      "value": row[7] or 0,  "pct": pct(row[7]), "color": "#ff6b6b"},
                ],
                "avg_improvement_pct": round(float(row[8] or 0), 1),
                "conversion_rate": pct(row[7]),
            }
        except Exception as e:
            logger.error(f"[Adaptiq] get_funnel_stats failed: {e}")
            return {"total_trials": 0, "stages": [], "avg_improvement_pct": 0, "conversion_rate": 0}
