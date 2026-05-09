import uuid
from datetime import date, datetime, timezone

from loguru import logger
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models import AgentJob, JobStatus, Post, Platform, PostStatus
from src.agents.strategy_agent import run_strategy_agent
from src.agents.content_writer_agent import run_content_writer_agent
from src.agents.visual_creator_agent import run_visual_creator_agent
from src.agents.scheduler_agent import run_scheduler_agent
from src.tools.visual_tool import generate_image


async def run_content_crew(week_start: date) -> dict:
    job_id = f"content_{week_start}"
    logger.info(f"[ContentCrew] Starting job_id={job_id}")

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(AgentJob).where(AgentJob.job_id == job_id))
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
        await db.commit()

        try:
            # Step 1: strategy
            logger.info("[ContentCrew] Step 1 — StrategyAgent")
            content_plan = run_strategy_agent(week_start=week_start)

            # Step 2: pick today's topic
            first_topic = content_plan.topics[0] if content_plan.topics else {}
            topic = first_topic.get("topic", "UPSC Preparation Tips")
            tone = first_topic.get("tone", "motivational")
            content_type = first_topic.get("content_type", "post")  # reel/carousel/story/post
            # Map content_type to Platform enum
            platform_map = {
                "reel": Platform.reel,
                "carousel": Platform.carousel,
                "story": Platform.story,
                "whatsapp": Platform.whatsapp,
                "telegram": Platform.telegram,
            }
            platform = platform_map.get(content_type, Platform.instagram)
            logger.info(f"[ContentCrew] Today's topic: '{topic}' tone='{tone}' type='{content_type}'")

            # Step 3: write captions
            logger.info("[ContentCrew] Step 3 — ContentWriterAgent")
            post_content = run_content_writer_agent(topic=topic, tone=tone)
            hashtag_block = " ".join(post_content.hashtags)
            caption_a = f"{post_content.caption_a}\n\n{hashtag_block}"
            caption_b = f"{post_content.caption_b}\n\n{hashtag_block}"

            # Step 4: visual prompt
            logger.info("[ContentCrew] Step 4 — VisualCreatorAgent")
            visual_asset = run_visual_creator_agent(caption=post_content.caption_a, topic=topic)

            # Step 5: generate image/video → upload to R2
            if content_type == "reel":
                logger.info("[ContentCrew] Step 5 — Reel: generating script + image")
                try:
                    from src.agents.reel_script_agent import run_reel_script_agent
                    reel_script = run_reel_script_agent(topic=topic, tone=tone)
                    # Use reel caption instead of regular caption
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
                logger.info("[ContentCrew] Step 5 — Generating image via Pollinations/Stability AI → R2")
                image_url = await generate_image(prompt=visual_asset.image_prompt, topic=topic)

            # Step 6: schedule
            logger.info("[ContentCrew] Step 6 — SchedulerAgent")
            schedule = run_scheduler_agent()

            # Step 7: save Post to DB
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
            await db.commit()

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
            job.status = JobStatus.failed
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            raise
