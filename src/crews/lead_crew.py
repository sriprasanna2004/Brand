import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models import AgentJob, JobStatus, Lead, LeadStatus, LeadSource, WhatsappSequence, SequenceStatus
from src.agents.lead_capture_agent import run_lead_capture_agent
from src.agents.lead_nurture_agent import run_lead_nurture_agent


async def run_lead_crew(
    ig_handle: str,
    message_text: str = "",
    day_number: int = 0,
) -> dict:
    job_id = f"lead_{ig_handle}_{day_number}"
    logger.info(f"[LeadCrew] Starting job_id={job_id}")

    async with AsyncSessionLocal() as db:
        existing_job = await db.scalar(select(AgentJob).where(AgentJob.job_id == job_id))
        if existing_job:
            job = existing_job
            job.status = JobStatus.running
        else:
            job = AgentJob(
                id=uuid.uuid4(),
                job_id=job_id,
                agent_name="LeadCrew",
                status=JobStatus.running,
                payload={"ig_handle": ig_handle, "day_number": day_number},
            )
            db.add(job)
        await db.commit()

        try:
            # ----------------------------------------------------------------
            # Day 0: Score the lead, send instant IG reply, schedule nurture
            # ----------------------------------------------------------------
            if day_number == 0:
                logger.info(f"[LeadCrew] Scoring lead @{ig_handle}")
                score = run_lead_capture_agent(message_text=message_text, ig_handle=ig_handle)
                now = datetime.now(timezone.utc)

                # Upsert lead
                lead = await db.scalar(select(Lead).where(Lead.ig_handle == ig_handle))
                is_new_lead = lead is None

                if lead:
                    lead.status = LeadStatus(score.status.value)
                    lead.updated_at = now
                    # Only re-enroll if not already in a sequence
                    if not lead.nurture_enrolled_at:
                        lead.nurture_enrolled_at = now
                        lead.intent_keywords = ",".join(score.intent_keywords_found) if score.intent_keywords_found else ""
                else:
                    lead = Lead(
                        id=uuid.uuid4(),
                        ig_handle=ig_handle,
                        status=LeadStatus(score.status.value),
                        source=LeadSource.instagram_dm,
                        nurture_enrolled_at=now,
                        intent_keywords=",".join(score.intent_keywords_found) if score.intent_keywords_found else "",
                    )
                    db.add(lead)

                await db.commit()
                await db.refresh(lead)

                # ── Step 1: Instant Instagram DM auto-reply ──────────────────
                # Fire-and-forget via Celery so the webhook returns immediately.
                # Only send if the lead has intent keywords (warm/hot).
                if score.auto_reply_message and score.status.value in ("hot", "warm"):
                    from src.scheduler.tasks import send_instant_ig_reply_task
                    send_instant_ig_reply_task.delay(
                        ig_user_id=ig_handle,
                        message=score.auto_reply_message,
                    )
                    logger.info(
                        f"[LeadCrew] Instant IG reply queued for @{ig_handle} "
                        f"(status={score.status.value})"
                    )

                # ── Step 2: Notify admin for hot leads ───────────────────────
                if score.should_notify_admin:
                    try:
                        from src.tools.telegram_tool import send_hot_lead_alert
                        await send_hot_lead_alert(
                            ig_handle=ig_handle,
                            keywords=score.intent_keywords_found,
                            auto_reply=score.auto_reply_message[:80],
                        )
                    except Exception as e:
                        logger.warning(f"[LeadCrew] Admin alert failed: {e}")

                # ── Step 3: Schedule Day 3 / 7 / 14 nurture via Celery ETA ──
                # Only schedule for new leads (first DM ever).
                # Re-DMs from existing enrolled leads are ignored to avoid duplicate sequences.
                if is_new_lead:
                    from src.scheduler.tasks import schedule_nurture_sequence
                    schedule_nurture_sequence(
                        ig_handle=ig_handle,
                        enrolled_at=lead.nurture_enrolled_at,
                    )
                    logger.info(
                        f"[LeadCrew] Nurture sequence scheduled for @{ig_handle} "
                        f"(Day 3/7/14 from {lead.nurture_enrolled_at.isoformat()})"
                    )

                job.status = JobStatus.success
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()

                logger.info(f"[LeadCrew] Lead @{ig_handle} saved, status={score.status}")
                return score.model_dump()

            # ----------------------------------------------------------------
            # Day 3 / 7 / 14: Send WhatsApp nurture message
            # ----------------------------------------------------------------
            if day_number not in (3, 7, 14):
                raise ValueError(f"day_number must be 0, 3, 7, or 14 — got {day_number}")

            lead = await db.scalar(select(Lead).where(Lead.ig_handle == ig_handle))
            if not lead:
                raise ValueError(f"Lead @{ig_handle} not found — run day_number=0 first")

            # Skip opted-out leads
            if lead.status == LeadStatus.opted_out:
                logger.info(f"[LeadCrew] @{ig_handle} opted out, skipping Day {day_number}")
                job.status = JobStatus.success
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return {"skipped": True, "reason": "opted_out", "ig_handle": ig_handle, "day_number": day_number}

            # Idempotency: skip if already sent
            already_sent = await db.scalar(
                select(WhatsappSequence).where(
                    WhatsappSequence.lead_id == lead.id,
                    WhatsappSequence.day_number == day_number,
                )
            )
            if already_sent:
                logger.warning(f"[LeadCrew] Day {day_number} already sent for @{ig_handle}, skipping")
                job.status = JobStatus.success
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return {"skipped": True, "reason": "already_sent", "ig_handle": ig_handle, "day_number": day_number}

            # Parse stored intent keywords to give the agent context
            intent_keywords = []
            if lead.intent_keywords:
                intent_keywords = [kw.strip() for kw in lead.intent_keywords.split(",") if kw.strip()]

            logger.info(f"[LeadCrew] Nurturing @{ig_handle} day={day_number}")
            nurture = run_lead_nurture_agent(
                lead_name=lead.name or ig_handle,
                day_number=day_number,
                lead_status=lead.status.value,
                intent_keywords=intent_keywords,
            )

            # Send via WhatsApp if phone is available
            wa_sent = False
            if lead.phone:
                from src.tools.whatsapp_tool import send_text_message
                wa_sent = await send_text_message(phone=lead.phone, message=nurture.message)
                logger.info(
                    f"[LeadCrew] WhatsApp Day {day_number} {'sent' if wa_sent else 'FAILED'} "
                    f"to {lead.phone}"
                )
            else:
                logger.warning(
                    f"[LeadCrew] No phone for @{ig_handle} — message generated but not sent via WhatsApp"
                )

            # Record sequence
            seq = WhatsappSequence(
                id=uuid.uuid4(),
                lead_id=lead.id,
                day_number=day_number,
                template_name=nurture.template_name,
                status=SequenceStatus.sent if wa_sent or not lead.phone else SequenceStatus.failed,
            )
            db.add(seq)

            job.status = JobStatus.success
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()

            logger.info(f"[LeadCrew] Day {day_number} nurture complete, template={nurture.template_name}")
            return {**nurture.model_dump(), "wa_sent": wa_sent}

        except Exception as e:
            logger.error(f"[LeadCrew] Failed job_id={job_id}: {e}")
            job.status = JobStatus.failed
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            raise
