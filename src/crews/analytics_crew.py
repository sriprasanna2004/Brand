import os
import json
import uuid
from datetime import date, datetime, timezone, timedelta

from loguru import logger
from sqlalchemy import create_engine, select as sa_select
from sqlalchemy.orm import sessionmaker

from src.models import AgentJob, JobStatus, PostAnalytics, Post
from src.agents.analytics_agent import run_analytics_agent

try:
    from src.redis_client import redis_client
    _redis = redis_client()
except Exception:
    _redis = None

REDIS_SUMMARY_KEY = "analytics:weekly_summary"
REDIS_STRATEGY_KEY = "strategy:performance_context"
SUMMARY_TTL = 7 * 24 * 3600
STRATEGY_TTL = 8 * 24 * 3600


def _get_sync_session():
    db_url = os.getenv("DATABASE_URL_SYNC", "")
    if not db_url:
        db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


async def run_analytics_crew() -> dict:
    today = date.today()
    job_id = f"analytics_{today}"
    logger.info(f"[AnalyticsCrew] Starting job_id={job_id}")

    db = _get_sync_session()
    try:
        existing_job = db.execute(
            sa_select(AgentJob).where(AgentJob.job_id == job_id)
        ).scalar_one_or_none()

        if existing_job:
            job = existing_job
            job.status = JobStatus.running
        else:
            job = AgentJob(
                id=uuid.uuid4(),
                job_id=job_id,
                agent_name="AnalyticsCrew",
                status=JobStatus.running,
                payload={"date": str(today)},
            )
            db.add(job)
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        raise

    try:
        # Step 1: fetch last 7 days of post_analytics joined with posts
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        rows = db.execute(
            sa_select(PostAnalytics, Post)
            .join(Post, PostAnalytics.post_id == Post.id)
            .where(PostAnalytics.recorded_at >= cutoff)
        ).all()

        posts_data = [
            {
                "post_id": str(pa.post_id),
                "content_type": post.platform.value,
                "reach": pa.reach,
                "saves": pa.saves,
                "dm_triggers": pa.dm_triggers,
                "story_views": pa.story_views,
                "link_clicks": pa.link_clicks,
                "winner_variant": pa.winner_variant,
                "scheduled_at": post.scheduled_at.isoformat(),
            }
            for pa, post in rows
        ]

        logger.info(f"[AnalyticsCrew] Fetched {len(posts_data)} analytics records")

        # Step 2: run analytics agent
        summary = run_analytics_agent(posts_data=posts_data if posts_data else [
            {"content_type": "reel", "reach": 0, "saves": 0, "dm_triggers": 0}
        ])

        if _redis:
            try:
                _redis.setex(REDIS_SUMMARY_KEY, SUMMARY_TTL, summary.model_dump_json())
                logger.info(f"[AnalyticsCrew] Summary cached in Redis key='{REDIS_SUMMARY_KEY}'")
                strategy_context = (
                    f"Last week top performing content: {json.dumps(summary.top_performers)}. "
                    f"Bottom performers: {json.dumps(summary.bottom_performers)}. "
                    f"Recommended mix for next week: {json.dumps(summary.recommended_content_mix)}. "
                    f"Increase top performer content types by 30%, reduce bottom performers."
                )
                _redis.setex(REDIS_STRATEGY_KEY, STRATEGY_TTL, strategy_context)
                logger.info(f"[AnalyticsCrew] Strategy context stored in Redis key='{REDIS_STRATEGY_KEY}'")
            except Exception as re:
                logger.warning(f"[AnalyticsCrew] Redis write failed: {re}")

        job.status = JobStatus.success
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"[AnalyticsCrew] Completed job_id={job_id}")
        return summary.model_dump()

    except Exception as e:
        logger.error(f"[AnalyticsCrew] Failed job_id={job_id}: {e}")
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
