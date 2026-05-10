import os
import uuid
from datetime import date, datetime, timezone

from loguru import logger
from sqlalchemy import create_engine, select as sa_select
from sqlalchemy.orm import sessionmaker

from src.models import AgentJob, JobStatus, Post, Platform, PostStatus
from src.agents.strategy_agent import run_strategy_agent
from src.agents.content_writer_agent import run_content_writer_agent
from src.agents.visual_creator_agent import run_visual_creator_agent
from src.agents.scheduler_agent import run_scheduler_agent
from src.tools.visual_tool import generate_image

# ---------------------------------------------------------------------------
# Sync DB setup — used inside Celery workers to avoid asyncpg event loop
# conflicts. The async engine is still used by the FastAPI endpoints.
# ---------------------------------------------------------------------------

def _get_sync_session():
    db_url = os.getenv("DATABASE_URL_SYNC", "")
    if not db_url:
        # Fallback: convert asyncpg URL to psycopg2
        db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


async def run_content_crew(week_start: date) -> dict:
    job_id = f"content_{week_start}"
    logger.info(f"[ContentCrew] Starting job_id={job_id}")

    # ── Step 0: upsert AgentJob (sync DB) ───────────────────────────────────
    db = _get_sync_session()
    try:
        existing = db.execute(
            sa_select(AgentJob).where(AgentJob.job_id == job_id)
        ).scalar_one_or_none()

        if existing:
            job = existing
            job.status = JobStatus.running
        else:
            job = AgentJob(
                id=uuid.uuid4(),
                job_id=job_id,
                agent_name="ContentCrew",
                status=JobStatus.running,
                payload={"week_start": str(week_start)},
            )
            db.add(job)
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        raise

    try:
        # ── Step 1: Strategy ─────────────────────────────────────────────────
        logger.info("[ContentCrew] Step 1 — StrategyAgent")
        content_plan = run_strategy_agent(week_start=week_start)

        # ── Step 2: Pick today's topic ───────────────────────────────────────
        first_topic = content_plan.topics[0] if content_plan.topics else {}
        topic = first_topic.get("topic", "UPSC Preparation Tips")
        tone = first_topic.get("tone", "motivational")
        content_type = first_topic.get("content_type", "post")
        platform_map = {
            "reel": Platform.reel,
            "carousel": Platform.carousel,
            "story": Platform.story,
            "whatsapp": Platform.whatsapp,
            "telegram": Platform.telegram,
        }
        platform = platform_map.get(content_type, Platform.instagram)
        logger.info(f"[ContentCrew] Today's topic: '{topic}' tone='{tone}' type='{content_type}'")

        # ── Step 3: Write captions ───────────────────────────────────────────
        logger.info("[ContentCrew] Step 3 — ContentWriterAgent")
        post_content = run_content_writer_agent(topic=topic, tone=tone)
        hashtag_block = " ".join(post_content.hashtags)
        caption_a = f"{post_content.caption_a}\n\n{hashtag_block}"
        caption_b = f"{post_content.caption_b}\n\n{hashtag_block}"

        # ── Step 4: Visual prompt ────────────────────────────────────────────
        logger.info("[ContentCrew] Step 4 — VisualCreatorAgent")
        visual_asset = run_visual_creator_agent(caption=post_content.caption_a, topic=topic)

        # ── Step 5: Generate image (async — keep as await) ───────────────────
        if content_type == "reel":
            logger.info("[ContentCrew] Step 5 — Reel: generating script + image")
            try:
                from src.agents.reel_script_agent import run_reel_script_agent
                reel_script = run_reel_script_agent(topic=topic, tone=tone)
                reel_caption = (
                    f"🎬 REEL SCRIPT\n\n"
                    f"🪝 {reel_script.hook}\n\n"
                    + "\n".join(f"✅ {pt}" for pt in reel_script.value_points)
                    + f"\n\n👉 {reel_script.cta}\n\n"
                    + " ".join(post_content.hashtags)
                )
                caption_a = reel_caption[:2200]
                caption_b = post_content.caption_b + "\n\n" + hashtag_block if post_content.caption_b else caption_a
                logger.info(f"[ContentCrew] Reel script generated, hook='{reel_script.hook[:40]}'")
            except Exception as e:
                logger.warning(f"[ContentCrew] Reel script failed ({e}), using regular caption")
            image_url = await generate_image(prompt=visual_asset.image_prompt, topic=topic)
        else:
            logger.info("[ContentCrew] Step 5 — Generating image via Pollinations/Stability AI -> R2")
            image_url = await generate_image(prompt=visual_asset.image_prompt, topic=topic)

        # ── Step 6: Schedule ─────────────────────────────────────────────────
        logger.info("[ContentCrew] Step 6 — SchedulerAgent")
        schedule = run_scheduler_agent()

        # ── Step 7: Save Post to DB (sync) ───────────────────────────────────
        post = Post(
            id=uuid.uuid4(),
            platform=platform,
            caption_a=caption_a,
            caption_b=caption_b,
            image_url=image_url,
            scheduled_at=schedule.post_time,
            status=PostStatus.pending,
        )
        db.add(post)

        job.status = JobStatus.success
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        result = {
            "post_id": str(post.id),
            "topic": topic,
            "caption_a": caption_a,
            "image_url": image_url,
            "scheduled_at": schedule.post_time.isoformat(),
        }
        logger.info(f"[ContentCrew] Completed — post_id={post.id} scheduled_at={schedule.post_time}")
        return result

    except Exception as e:
        logger.error(f"[ContentCrew] Failed job_id={job_id}: {e}")
        try:
            job.status = JobStatus.failed
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()
