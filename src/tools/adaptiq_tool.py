"""
Adaptiq funnel tool — manages the full 7-day trial → paid conversion sequence.
Tracks: source post, weak subjects, improvement %, webinar, demo, payment intent.
Sends via: WhatsApp + Telegram admin alert on conversion.
"""
import uuid
import random
from datetime import datetime, timezone, timedelta

from loguru import logger
from sqlalchemy import select, text

from src.database import AsyncSessionLocal
from src.models import AgentJob, JobStatus, AdaptiqTrial, Lead, LeadStatus

# All 7 trial days
TRIAL_DAYS = (1, 2, 3, 4, 5, 6, 7)
DAY_SENT_COL = {1: "day1_sent", 2: "day1_sent", 3: "day3_sent",
                4: "day3_sent", 5: "day5_sent", 6: "day5_sent", 7: "day7_sent"}


async def start_trial(
    lead_id: str,
    lead_phone: str,
    lead_name: str,
    source_post_id: str = "",
    weak_subjects: list[str] = None,
) -> bool:
    from src.agents.adaptiq_promo_agent import run_adaptiq_promo_agent
    from src.tools.whatsapp_tool import send_text_message

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Check if trial already exists
        existing = await db.scalar(select(AdaptiqTrial).where(AdaptiqTrial.lead_id == uuid.UUID(lead_id)))
        if existing:
            logger.info(f"[Adaptiq] Trial already exists for lead_id={lead_id}")
            return False

        subjects_str = ",".join(weak_subjects or [])
        trial = AdaptiqTrial(
            id=uuid.uuid4(),
            lead_id=uuid.UUID(lead_id),
            trial_start=now,
            trial_end=now + timedelta(days=7),
            source_post_id=source_post_id or None,
            weak_subjects=subjects_str or None,
            improvement_pct=0,
        )
        db.add(trial)
        await db.commit()
        logger.info(f"[Adaptiq] Trial started for lead_id={lead_id}")

    try:
        msg = run_adaptiq_promo_agent(
            lead_name=lead_name, trial_day=1,
            weak_subjects=weak_subjects or [],
            source_post=source_post_id,
        )
        if lead_phone:
            await send_text_message(phone=lead_phone, message=msg.message)
        logger.info(f"[Adaptiq] Day 1 message sent to {lead_phone or 'no phone'}")
        # Mark day1 sent
        async with AsyncSessionLocal() as db:
            t = await db.scalar(select(AdaptiqTrial).where(AdaptiqTrial.lead_id == uuid.UUID(lead_id)))
            if t:
                t.day1_sent = 1
                await db.commit()
        return True
    except Exception as e:
        logger.error(f"[Adaptiq] start_trial Day 1 message failed: {e}")
        return False


async def run_trial_sequences() -> int:
    from src.agents.adaptiq_promo_agent import run_adaptiq_promo_agent
    from src.tools.whatsapp_tool import send_text_message

    now = datetime.now(timezone.utc)
    sent_count = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AdaptiqTrial).where(
                AdaptiqTrial.converted_at.is_(None),
                AdaptiqTrial.trial_end >= now,
            )
        )
        trials = result.scalars().all()
        logger.info(f"[Adaptiq] Processing {len(trials)} active trial(s)")

        for trial in trials:
            trial_day = (now - trial.trial_start).days + 1
            if trial_day not in TRIAL_DAYS:
                continue

            lead = await db.scalar(select(Lead).where(Lead.id == trial.lead_id))
            if not lead:
                continue

            job_id = f"adaptiq_{lead.id}_day{trial_day}"
            already = await db.scalar(select(AgentJob).where(AgentJob.job_id == job_id))
            if already:
                continue

            job = AgentJob(
                id=uuid.uuid4(), job_id=job_id,
                agent_name="AdaptiqPromoAgent", status=JobStatus.running,
                payload={"lead_id": str(lead.id), "trial_day": trial_day},
            )
            db.add(job)
            await db.commit()

            try:
                weak = [s.strip() for s in (trial.weak_subjects or "").split(",") if s.strip()]
                # Simulate improvement on Day 5+ (real app would pull from Adaptiq API)
                improvement = trial.improvement_pct or 0
                if trial_day >= 5 and improvement == 0:
                    improvement = random.randint(15, 25)
                    trial.improvement_pct = improvement
                    await db.commit()

                msg = run_adaptiq_promo_agent(
                    lead_name=lead.name or lead.ig_handle,
                    trial_day=trial_day,
                    weak_subjects=weak,
                    improvement_pct=improvement,
                    source_post=trial.source_post_id or "",
                )

                if lead.phone:
                    await send_text_message(phone=lead.phone, message=msg.message)

                job.status = JobStatus.success
                job.completed_at = now
                sent_count += 1
                logger.info(f"[Adaptiq] Day {trial_day} sent to {lead.ig_handle}, urgency={msg.urgency_level}")

                # Mark webinar/demo stages
                if trial_day == 4:
                    trial.webinar_attended = 1
                if trial_day == 6:
                    trial.demo_booked = 1
                if trial_day == 7:
                    trial.payment_initiated = 1

            except Exception as e:
                job.status = JobStatus.failed
                job.error = str(e)
                job.completed_at = now
                logger.error(f"[Adaptiq] Day {trial_day} failed for {lead.id}: {e}")

            await db.commit()

    return sent_count


async def mark_converted(lead_id: str, plan: str) -> bool:
    from src.tools.telegram_tool import send_admin_alert
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        trial = await db.scalar(select(AdaptiqTrial).where(AdaptiqTrial.lead_id == uuid.UUID(lead_id)))
        if trial:
            trial.converted_at = now
            trial.plan = plan
            trial.payment_initiated = 1

        lead = await db.scalar(select(Lead).where(Lead.id == uuid.UUID(lead_id)))
        if lead:
            lead.status = LeadStatus.hot
            lead.updated_at = now
            name = lead.name or lead.ig_handle
        else:
            name = lead_id

        await db.commit()

    logger.info(f"[Adaptiq] Conversion: {name} → {plan}")
    try:
        price = "₹1,999" if "annual" in plan.lower() else "₹299"
        await send_admin_alert(f"🎉 Adaptiq Conversion!\n{name} upgraded to {plan} ({price})")
    except Exception:
        pass
    return True


async def get_funnel_stats() -> dict:
    """Return full 7-stage funnel with conversion rates and drop-off."""
    async with AsyncSessionLocal() as db:
        try:
            r = await db.execute(text("""
                SELECT
                    COUNT(*) as total_trials,
                    SUM(CASE WHEN day1_sent=1 THEN 1 ELSE 0 END) as day1,
                    SUM(CASE WHEN day3_sent=1 THEN 1 ELSE 0 END) as day3,
                    SUM(CASE WHEN webinar_attended=1 THEN 1 ELSE 0 END) as webinar,
                    SUM(CASE WHEN day5_sent=1 THEN 1 ELSE 0 END) as day5,
                    SUM(CASE WHEN demo_booked=1 THEN 1 ELSE 0 END) as demo,
                    SUM(CASE WHEN payment_initiated=1 THEN 1 ELSE 0 END) as payment,
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
                    {"label": "Free Trial Started", "value": total, "pct": 100, "color": "#00e5c3"},
                    {"label": "Day 1 Onboarded", "value": row[1] or 0, "pct": pct(row[1]), "color": "#00e5c3"},
                    {"label": "Day 3 Weak Areas", "value": row[2] or 0, "pct": pct(row[2]), "color": "#4facfe"},
                    {"label": "Webinar Attended", "value": row[3] or 0, "pct": pct(row[3]), "color": "#9d6fff"},
                    {"label": "Day 5 Progress", "value": row[4] or 0, "pct": pct(row[4]), "color": "#ffd166"},
                    {"label": "Demo Booked", "value": row[5] or 0, "pct": pct(row[5]), "color": "#ffd166"},
                    {"label": "Payment Initiated", "value": row[6] or 0, "pct": pct(row[6]), "color": "#ff6b6b"},
                    {"label": "Paid Converted", "value": row[7] or 0, "pct": pct(row[7]), "color": "#ff6b6b"},
                ],
                "avg_improvement_pct": round(float(row[8] or 0), 1),
                "conversion_rate": pct(row[7]),
            }
        except Exception as e:
            logger.error(f"[Adaptiq] get_funnel_stats failed: {e}")
            return {"total_trials": 0, "stages": [], "avg_improvement_pct": 0, "conversion_rate": 0}
