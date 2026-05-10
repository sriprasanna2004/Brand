import os
import asyncio
import subprocess
from datetime import date, datetime, timezone

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from loguru import logger


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LeadTaskRequest(BaseModel):
    ig_handle: str
    message_text: str = "what are the fees for batch?"
    day_number: int = 0

class ApprovePostRequest(BaseModel):
    post_id: str

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
sentry_dsn = os.getenv("SENTRY_DSN", "")
if sentry_dsn and sentry_dsn != "REPLACE_ME":
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=os.getenv("ENVIRONMENT", "development"),
        traces_sample_rate=0.2,
    )

# ---------------------------------------------------------------------------
# Loguru
# ---------------------------------------------------------------------------
log_level = os.getenv("LOG_LEVEL", "INFO")
logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    level=log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
    colorize=True,
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="BrandIQ", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    logger.info("Running alembic upgrade head...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Alembic migration failed:\n{result.stderr}")
    else:
        logger.info("Migrations applied successfully.")

    # Ensure all tables exist (fallback for Railway)
    try:
        from src.database import engine, Base
        import src.models  # noqa
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Tables verified/created.")
    except Exception as e:
        logger.error(f"Table creation failed: {e}")

    from src.scheduler.cron_jobs import start_scheduler
    start_scheduler()

    # Auto-run pipeline on startup (non-blocking)
    import asyncio
    async def _startup_pipeline():
        await asyncio.sleep(8)
        logger.info("[Startup] Queuing initial content crew...")
        try:
            from src.scheduler.tasks import run_content_crew_task
            run_content_crew_task.delay()
            logger.info("[Startup] Content crew queued.")
        except Exception as e:
            logger.warning(f"[Startup] Could not queue content crew: {e}")
    asyncio.create_task(_startup_pipeline())


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Manual task triggers
# ---------------------------------------------------------------------------

@app.post("/tasks/content")
async def trigger_content_crew():
    from src.scheduler.tasks import run_content_crew_task
    task = run_content_crew_task.delay()
    logger.info(f"[API] Content crew triggered, task_id={task.id}")
    return {"task_id": task.id, "status": "queued"}


@app.post("/tasks/analytics")
async def trigger_analytics_crew():
    from src.scheduler.tasks import run_analytics_crew_task
    task = run_analytics_crew_task.delay()
    logger.info(f"[API] Analytics crew triggered, task_id={task.id}")
    return {"task_id": task.id, "status": "queued"}


@app.post("/tasks/lead")
async def trigger_lead_crew(body: LeadTaskRequest):
    from src.scheduler.tasks import run_lead_crew_task
    task = run_lead_crew_task.delay(
        ig_handle=body.ig_handle,
        message_text=body.message_text,
        day_number=body.day_number,
    )
    return {"task_id": task.id, "status": "queued", "ig_handle": body.ig_handle, "day_number": body.day_number}


@app.get("/posts")
async def list_posts(status: str = None, limit: int = 20, upcoming_only: bool = False):
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import Post, PostStatus
    from datetime import timezone
    async with AsyncSessionLocal() as db:
        q = select(Post).order_by(Post.scheduled_at.desc()).limit(limit)
        if status:
            q = q.where(Post.status == PostStatus(status))
        if upcoming_only:
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            q = q.where(Post.scheduled_at >= today_start)
        result = await db.execute(q)
        posts = result.scalars().all()
        return [
            {
                "id": str(p.id), "platform": p.platform.value,
                "caption_a": p.caption_a[:80], "status": p.status.value,
                "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
            }
            for p in posts
        ]


@app.post("/posts/approve")
async def approve_post(body: ApprovePostRequest):
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import Post, PostStatus
    import uuid
    async with AsyncSessionLocal() as db:
        post = await db.scalar(select(Post).where(Post.id == uuid.UUID(body.post_id)))
        if not post:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Post not found")
        post.status = PostStatus.approved
        await db.commit()
        return {"post_id": body.post_id, "status": "approved"}


@app.post("/posts/publish/{post_id}")
async def publish_post_now(post_id: str):
    from src.tools.post_publisher import publish_single_post
    success = await publish_single_post(post_id)
    if success:
        return {"post_id": post_id, "published": True}
    return {"post_id": post_id, "published": False, "error": "Publish failed"}


@app.get("/leads")
async def list_leads(status: str = None, limit: int = 50):
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import Lead, LeadStatus
    async with AsyncSessionLocal() as db:
        q = select(Lead).order_by(Lead.created_at.desc()).limit(limit)
        if status:
            q = q.where(Lead.status == LeadStatus(status))
        result = await db.execute(q)
        leads = result.scalars().all()
        return [
            {
                "id": str(l.id), "ig_handle": l.ig_handle, "name": l.name,
                "phone": l.phone, "status": l.status.value, "source": l.source.value,
                "created_at": l.created_at.isoformat(),
            }
            for l in leads
        ]


@app.get("/stats/kpis")
async def get_kpis():
    from sqlalchemy import select, func, text
    from src.database import AsyncSessionLocal
    from datetime import timezone
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with AsyncSessionLocal() as db:
        def q(sql, params=None):
            return db.execute(text(sql), params or {})
        try:
            r = await q("SELECT COUNT(*) FROM posts WHERE posted_at >= :t AND status = 'posted'", {"t": today})
            posts_today = r.scalar() or 0
        except Exception: await db.rollback(); posts_today = 0
        try:
            r = await q("SELECT COUNT(*) FROM leads WHERE created_at >= :t", {"t": today})
            new_leads = r.scalar() or 0
        except Exception: await db.rollback(); new_leads = 0
        try:
            r = await q("SELECT COUNT(*) FROM leads WHERE status = 'hot' AND created_at >= :t", {"t": today})
            hot_leads = r.scalar() or 0
        except Exception: await db.rollback(); hot_leads = 0
        try:
            r = await q("SELECT COUNT(*) FROM whatsapp_sequences WHERE sent_at >= :t AND status = 'sent'", {"t": today})
            wa_sent = r.scalar() or 0
        except Exception: await db.rollback(); wa_sent = 0
        try:
            r = await q("SELECT COUNT(*) FROM adaptiq_trials WHERE trial_start >= :t", {"t": today})
            trials = r.scalar() or 0
        except Exception: await db.rollback(); trials = 0
        try:
            r = await q("SELECT COUNT(*) FROM leads")
            total_leads = r.scalar() or 0
        except Exception: await db.rollback(); total_leads = 0
        try:
            r = await q("SELECT COUNT(*) FROM posts WHERE status = 'posted'")
            total_posts = r.scalar() or 0
        except Exception: await db.rollback(); total_posts = 0
    return {
        "posts_today": posts_today, "new_leads": new_leads, "hot_leads": hot_leads,
        "wa_sent": wa_sent, "trials_today": trials,
        "total_leads": total_leads, "total_posts": total_posts,
    }


@app.get("/stats/analytics-summary")
async def get_analytics_summary():
    """Return analytics summary from Redis or latest AgentJob payload."""
    import json, re as _re
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        try:
            import redis as rl
            url_fixed = _re.sub(r'ssl_cert_reqs=CERT_NONE', 'ssl_cert_reqs=none', redis_url, flags=_re.IGNORECASE)
            r = rl.from_url(url_fixed, decode_responses=True)
            raw = r.get("analytics:weekly_summary")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return {"error": "no_data"}


@app.get("/stats/agent-status")
async def get_agent_status():
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import AgentJob
    from datetime import timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    agents = [
        "ContentCrew","LeadCrew","AnalyticsCrew",
        "StrategyAgent","ContentWriterAgent","VisualCreatorAgent",
        "SchedulerAgent","LeadCaptureAgent","LeadNurtureAgent",
        "ReelScriptAgent","AnalyticsAgent","AdaptiqPromoAgent",
    ]
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentJob)
            .where(AgentJob.created_at >= cutoff)
            .order_by(AgentJob.created_at.desc())
        )
        jobs = result.scalars().all()
    latest = {}
    for j in jobs:
        if j.agent_name not in latest:
            latest[j.agent_name] = {"agent_name": j.agent_name, "status": j.status.value, "job_id": j.job_id, "created_at": j.created_at.isoformat()}
    return list(latest.values())


@app.get("/stats/live-feed")
async def get_live_feed():
    from sqlalchemy import select, or_
    from src.database import AsyncSessionLocal
    from src.models import AgentJob, Lead, LeadStatus, Post, PostStatus
    from datetime import timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    events = []
    async with AsyncSessionLocal() as db:
        posts = await db.execute(select(Post).where(Post.posted_at >= cutoff, Post.status == PostStatus.posted).order_by(Post.posted_at.desc()).limit(5))
        for p in posts.scalars().all():
            events.append({"type": "post", "icon": "✓", "text": f"Post published — \"{p.caption_a[:40]}...\"", "time": p.posted_at.isoformat(), "color": "#00e5c3"})
        leads = await db.execute(select(Lead).where(Lead.created_at >= cutoff, Lead.status == LeadStatus.hot).order_by(Lead.created_at.desc()).limit(5))
        for l in leads.scalars().all():
            events.append({"type": "lead", "icon": "💬", "text": f"Hot lead — @{l.ig_handle}", "time": l.created_at.isoformat(), "color": "#9d6fff"})
    events.sort(key=lambda x: x["time"], reverse=True)
    return events[:8]


@app.get("/stats/reach")
async def get_reach():
    from sqlalchemy import select, func
    from src.database import AsyncSessionLocal
    from src.models import PostAnalytics
    from datetime import timezone, timedelta
    async with AsyncSessionLocal() as db:
        rows = []
        for i in range(6, -1, -1):
            day = datetime.now(timezone.utc) - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59)
            reach = await db.scalar(select(func.sum(PostAnalytics.reach)).where(PostAnalytics.recorded_at >= day_start, PostAnalytics.recorded_at <= day_end)) or 0
            rows.append({"day": day.strftime("%a"), "reach": reach})
    return rows


@app.get("/stats/funnels")
async def get_funnels():
    from sqlalchemy import select, func
    from src.database import AsyncSessionLocal
    from src.models import Lead, LeadStatus, AdaptiqTrial, PostAnalytics
    from datetime import timezone
    today = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with AsyncSessionLocal() as db:
        total_leads = await db.scalar(select(func.count(Lead.id)).where(Lead.created_at >= today)) or 0
        hot_leads = await db.scalar(select(func.count(Lead.id)).where(Lead.status == LeadStatus.hot, Lead.created_at >= today)) or 0
        trials = await db.scalar(select(func.count(AdaptiqTrial.id)).where(AdaptiqTrial.trial_start >= today)) or 0
        converted = await db.scalar(select(func.count(AdaptiqTrial.id)).where(AdaptiqTrial.converted_at.isnot(None), AdaptiqTrial.trial_start >= today)) or 0
        total_reach = await db.scalar(select(func.sum(PostAnalytics.reach)).where(PostAnalytics.recorded_at >= today)) or 0
    return {
        "lead_funnel": [
            {"label": "Reached", "value": total_reach or 0, "pct": 100},
            {"label": "Engaged", "value": int(total_reach * 0.03) if total_reach else 0, "pct": 75},
            {"label": "Enquired", "value": total_leads, "pct": 48},
            {"label": "Trial", "value": trials, "pct": 28},
            {"label": "Admitted", "value": hot_leads, "pct": 12},
        ],
        "adaptiq_funnel": [
            {"label": "Promo Views", "value": total_reach or 0, "pct": 100},
            {"label": "Link Clicks", "value": int(total_reach * 0.004) if total_reach else 0, "pct": 70},
            {"label": "Free Trial", "value": trials, "pct": 42},
            {"label": "Day 5 Active", "value": int(trials * 0.63) if trials else 0, "pct": 26},
            {"label": "Converted", "value": converted, "pct": 10},
        ],
    }


@app.get("/calendar")
async def get_calendar():
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import Post
    from datetime import timezone, timedelta
    today = datetime.now(timezone.utc)
    # Show 3 days back + 7 days forward so recent posts always appear
    week_start = today - timedelta(days=3)
    week_end = today + timedelta(days=7)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post)
            .where(Post.scheduled_at >= week_start, Post.scheduled_at <= week_end)
            .order_by(Post.scheduled_at)
        )
        posts = result.scalars().all()
    calendar = {}
    for p in posts:
        day = p.scheduled_at.strftime("%Y-%m-%d")
        if day not in calendar:
            calendar[day] = []
        calendar[day].append({
            "caption": p.caption_a[:30],
            "platform": p.platform.value,
            "status": p.status.value,
        })
    return calendar


@app.get("/stats/agent-jobs")
async def get_agent_jobs(limit: int = 20):
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import AgentJob
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentJob).order_by(AgentJob.created_at.desc()).limit(limit))
        jobs = result.scalars().all()
        return [
            {
                "job_id": j.job_id, "agent_name": j.agent_name, "status": j.status.value,
                "created_at": j.created_at.isoformat(),
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "error": j.error,
            }
            for j in jobs
        ]


# ---------------------------------------------------------------------------
# Run Pipeline (synchronous — no Celery, runs all agents in sequence)
# ---------------------------------------------------------------------------

@app.post("/run-pipeline")
async def run_pipeline():
    """Synchronous full pipeline: Strategy → Content → Visual → Schedule → 3 dummy leads → Analytics."""
    from datetime import date
    results = {}
    errors = []

    logger.info("[Pipeline] Starting full pipeline run")

    # Step 1: Content pipeline
    try:
        from src.agents.strategy_agent import run_strategy_agent
        plan = run_strategy_agent(week_start=date.today())
        topic = plan.topics[0].get("topic", "UPSC Preparation") if plan.topics else "UPSC Preparation"
        tone = plan.topics[0].get("tone", "motivational") if plan.topics else "motivational"
        results["strategy"] = {"topic": topic, "tone": tone, "topics_count": len(plan.topics)}
        logger.info(f"[Pipeline] StrategyAgent completed — topic: {topic}")
    except Exception as e:
        errors.append(f"StrategyAgent: {e}"); topic = "UPSC Preparation Tips"; tone = "motivational"
        logger.error(f"[Pipeline] StrategyAgent failed: {e}")

    try:
        from src.agents.content_writer_agent import run_content_writer_agent
        content = run_content_writer_agent(topic=topic, tone=tone)
        results["content"] = {"caption_a": content.caption_a[:80], "hashtags_count": len(content.hashtags)}
        logger.info("[Pipeline] ContentWriterAgent completed")
    except Exception as e:
        errors.append(f"ContentWriterAgent: {e}"); content = None
        logger.error(f"[Pipeline] ContentWriterAgent failed: {e}")

    try:
        from src.agents.visual_creator_agent import run_visual_creator_agent
        caption_text = content.caption_a if content else topic
        visual = run_visual_creator_agent(caption=caption_text, topic=topic)
        results["visual"] = {"overlay_text": visual.overlay_text, "watermark": visual.watermark_text}
        logger.info("[Pipeline] VisualCreatorAgent completed")
    except Exception as e:
        errors.append(f"VisualCreatorAgent: {e}")
        logger.error(f"[Pipeline] VisualCreatorAgent failed: {e}")

    try:
        from src.agents.scheduler_agent import run_scheduler_agent
        schedule = run_scheduler_agent()
        results["schedule"] = {"post_time": schedule.post_time.isoformat(), "expected_reach": schedule.expected_reach}
        logger.info(f"[Pipeline] SchedulerAgent completed — post_time: {schedule.post_time}")
    except Exception as e:
        errors.append(f"SchedulerAgent: {e}")
        logger.error(f"[Pipeline] SchedulerAgent failed: {e}")

    # Step 2: Save post to DB
    try:
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.database import AsyncSessionLocal
        from src.models import Post, Platform, PostStatus
        import uuid
        from datetime import timezone, timedelta
        caption_a = (content.caption_a + "\n\n" + " ".join(content.hashtags)) if content else topic
        caption_b = content.caption_b if content else None
        post_time = schedule.post_time if "schedule" in results else datetime.now(timezone.utc) + timedelta(hours=13)
        async with AsyncSessionLocal() as db:
            post = Post(
                id=uuid.uuid4(), platform=Platform.instagram,
                caption_a=caption_a, caption_b=caption_b,
                image_url="https://via.placeholder.com/1024x1024.png?text=TOPPER+IAS",
                scheduled_at=post_time, status=PostStatus.pending,
            )
            db.add(post)
            await db.commit()
            results["post_saved"] = {"post_id": str(post.id), "status": "pending"}
            logger.info(f"[Pipeline] Post saved to DB: {post.id}")
    except Exception as e:
        errors.append(f"SavePost: {e}")
        logger.error(f"[Pipeline] SavePost failed: {e}")

    # Step 3: Simulate 3 leads
    dummy_leads = [
        ("pipeline_lead_1", "what are the fees for the full batch?"),
        ("pipeline_lead_2", "when does the next batch start for prelims?"),
        ("pipeline_lead_3", "how to join TOPPER IAS online course?"),
    ]
    lead_results = []
    for handle, message in dummy_leads:
        try:
            from src.agents.lead_capture_agent import run_lead_capture_agent
            score = run_lead_capture_agent(message_text=message, ig_handle=handle)
            from src.database import AsyncSessionLocal
            from src.models import Lead, LeadStatus, LeadSource
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select
                existing = await db.scalar(select(Lead).where(Lead.ig_handle == handle))
                if not existing:
                    lead = Lead(id=uuid.uuid4(), ig_handle=handle, status=LeadStatus(score.status.value), source=LeadSource.instagram_dm)
                    db.add(lead)
                    await db.commit()
            lead_results.append({"handle": handle, "status": score.status.value, "keywords": score.intent_keywords_found})
            logger.info(f"[Pipeline] Lead {handle} scored as {score.status.value}")
        except Exception as e:
            errors.append(f"Lead {handle}: {e}")
            logger.error(f"[Pipeline] Lead {handle} failed: {e}")
    results["leads"] = lead_results

    # Step 4: LeadNurture Day 3 preview for each lead (Day 3 is the first WhatsApp touch)
    nurture_results = []
    for handle, _ in dummy_leads:
        try:
            from src.agents.lead_nurture_agent import run_lead_nurture_agent
            msg = run_lead_nurture_agent(lead_name=handle, day_number=3, lead_status="hot")
            nurture_results.append({"handle": handle, "template": msg.template_name, "message_preview": msg.message[:60]})
            logger.info(f"[Pipeline] Nurture Day 3 preview generated for {handle}")
        except Exception as e:
            errors.append(f"Nurture {handle}: {e}")
    results["nurture"] = nurture_results

    # Step 5: Analytics
    try:
        from src.agents.analytics_agent import run_analytics_agent
        analytics = run_analytics_agent(posts_data=[{"content_type": "reel", "reach": 0, "saves": 0, "dm_triggers": len(lead_results)}])
        results["analytics"] = {"insight": analytics.insight_text[:100], "weekly_reach": analytics.weekly_reach_total}
        logger.info("[Pipeline] AnalyticsAgent completed")
    except Exception as e:
        errors.append(f"AnalyticsAgent: {e}")
        logger.error(f"[Pipeline] AnalyticsAgent failed: {e}")

    logger.info(f"[Pipeline] Completed — {len(errors)} errors")
    return {"status": "completed", "results": results, "errors": errors, "agents_run": len(results)}


@app.post("/simulate-lead")
async def simulate_lead():
    """
    Create 3 dummy leads, run LeadCaptureAgent (Day 0), preview Day 3 nurture message.
    In production, Day 3/7/14 messages are sent automatically via Celery ETA tasks
    scheduled when the lead is first captured.
    """
    import uuid
    from datetime import timezone
    dummy = [
        ("sim_rahul_upsc", "what are the fees for the full batch?"),
        ("sim_priya_ias", "when does the prelims batch start?"),
        ("sim_ankit_civil", "how to enroll in TOPPER IAS online course?"),
    ]
    results = []
    for handle, message in dummy:
        result = {"handle": handle, "message": message}
        try:
            from src.agents.lead_capture_agent import run_lead_capture_agent
            score = run_lead_capture_agent(message_text=message, ig_handle=handle)
            result["score"] = score.status.value
            result["keywords"] = score.intent_keywords_found
            result["auto_reply"] = score.auto_reply_message[:80]
            from src.database import AsyncSessionLocal
            from src.models import Lead, LeadStatus, LeadSource
            from sqlalchemy import select
            now = datetime.now(timezone.utc)
            async with AsyncSessionLocal() as db:
                existing = await db.scalar(select(Lead).where(Lead.ig_handle == handle))
                if not existing:
                    lead = Lead(
                        id=uuid.uuid4(),
                        ig_handle=handle,
                        status=LeadStatus(score.status.value),
                        source=LeadSource.instagram_dm,
                        nurture_enrolled_at=now,
                        intent_keywords=",".join(score.intent_keywords_found),
                    )
                    db.add(lead)
                    await db.commit()
            logger.info(f"[SimulateLead] {handle} → {score.status.value}")
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"[SimulateLead] {handle} failed: {e}")
        # Preview Day 3 message (the first WhatsApp touch in the sequence)
        try:
            from src.agents.lead_nurture_agent import run_lead_nurture_agent
            nurture = run_lead_nurture_agent(
                lead_name=handle,
                day_number=3,
                lead_status=result.get("score", "warm"),
                intent_keywords=result.get("keywords", []),
            )
            result["nurture_day3_preview"] = nurture.message[:80]
            result["nurture_cta"] = nurture.cta_link
        except Exception as e:
            result["nurture_error"] = str(e)
        results.append(result)
    return {"status": "ok", "leads_simulated": len(results), "results": results}


@app.get("/get-dashboard-data")
async def get_dashboard_data():
    """Unified endpoint: posts + leads + metrics + agent logs."""
    from sqlalchemy import text
    from src.database import AsyncSessionLocal
    from datetime import timezone
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    data = {}
    async with AsyncSessionLocal() as db:
        try:
            r = await db.execute(text("SELECT id::text,platform,LEFT(caption_a,60) as caption,status,scheduled_at::text FROM posts ORDER BY created_at DESC LIMIT 10"))
            data["posts"] = [dict(row._mapping) for row in r.fetchall()]
        except Exception: data["posts"] = []
        try:
            r = await db.execute(text("SELECT id::text,ig_handle,name,status,source,created_at::text FROM leads ORDER BY created_at DESC LIMIT 20"))
            data["leads"] = [dict(row._mapping) for row in r.fetchall()]
        except Exception: data["leads"] = []
        try:
            r = await db.execute(text("SELECT SUM(reach) as total_reach, SUM(dm_triggers) as total_leads, SUM(link_clicks) as total_clicks FROM post_analytics"))
            row = r.fetchone()
            data["metrics"] = {"total_reach": row[0] or 0, "total_leads": row[1] or 0, "total_clicks": row[2] or 0}
        except Exception: data["metrics"] = {"total_reach": 0, "total_leads": 0, "total_clicks": 0}
        try:
            r = await db.execute(text("SELECT agent_name,status,created_at::text,completed_at::text,error FROM agent_jobs ORDER BY created_at DESC LIMIT 20"))
            data["logs"] = [dict(row._mapping) for row in r.fetchall()]
        except Exception: data["logs"] = []
    return data


@app.get("/adaptiq")
@app.get("/adaptiq/")
async def adaptiq_landing():
    """Serve the Adaptiq free trial landing page."""
    from fastapi.responses import FileResponse
    import os
    html_path = os.path.join(os.path.dirname(__file__), "adaptiq_landing.html")
    if not os.path.exists(html_path):
        return {"error": f"HTML file not found at {html_path}"}
    return FileResponse(html_path, media_type="text/html")


class AdaptiqRegisterRequest(BaseModel):
    lead_name: str
    phone: str


@app.post("/adaptiq/register")
async def adaptiq_register(body: AdaptiqRegisterRequest):
    """
    One-shot endpoint for the landing page:
    1. Creates or finds the lead by phone number
    2. Starts the Adaptiq trial
    3. Sends Day 1 WhatsApp message
    """
    import uuid as _uuid
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import Lead, LeadStatus, LeadSource
    from src.tools.adaptiq_tool import start_trial

    # Normalise phone
    phone = body.phone.strip()
    if not phone.startswith("+"):
        phone = "+91" + phone.lstrip("0")

    async with AsyncSessionLocal() as db:
        # Find existing lead by phone or create new one
        lead = await db.scalar(select(Lead).where(Lead.phone == phone))
        if not lead:
            lead = Lead(
                id=_uuid.uuid4(),
                ig_handle=f"adaptiq_{phone[-10:]}",
                phone=phone,
                name=body.lead_name,
                status=LeadStatus.warm,
                source=LeadSource.instagram_dm,
            )
            db.add(lead)
            await db.commit()
            await db.refresh(lead)
        else:
            # Update name if provided
            if body.lead_name and not lead.name:
                lead.name = body.lead_name
                await db.commit()

    success = await start_trial(
        lead_id=str(lead.id),
        lead_phone=phone,
        lead_name=body.lead_name or lead.name or phone,
    )

    if success:
        logger.info(f"[AdaptiqRegister] Trial started for {phone} ({body.lead_name})")
        return {"success": True, "message": "Trial started! Check WhatsApp for your Day 1 message."}
    else:
        # Trial already exists — still return success
        logger.info(f"[AdaptiqRegister] Trial already exists for {phone}")
        return {"success": True, "message": "You already have an active trial! Check WhatsApp."}


@app.get("/adaptiq/funnel")
async def adaptiq_funnel():
    """Full 7-stage Adaptiq funnel with conversion rates."""
    from src.tools.adaptiq_tool import get_funnel_stats
    return await get_funnel_stats()


class StartTrialRequest(BaseModel):
    lead_id: str
    lead_phone: str = ""
    lead_name: str
    source_post_id: str = ""
    weak_subjects: list[str] = []


@app.post("/adaptiq/start-trial")
async def start_trial_endpoint(body: StartTrialRequest):
    from src.tools.adaptiq_tool import start_trial
    success = await start_trial(
        lead_id=body.lead_id, lead_phone=body.lead_phone,
        lead_name=body.lead_name, source_post_id=body.source_post_id,
        weak_subjects=body.weak_subjects,
    )
    return {"success": success}


class ConvertRequest(BaseModel):
    lead_id: str
    plan: str = "monthly"


@app.post("/adaptiq/convert")
async def convert_trial(body: ConvertRequest):
    from src.tools.adaptiq_tool import mark_converted
    success = await mark_converted(lead_id=body.lead_id, plan=body.plan)
    return {"success": success}


@app.get("/adaptiq/trials")
async def list_trials(limit: int = 20):
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models import AdaptiqTrial, Lead
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AdaptiqTrial, Lead)
            .join(Lead, AdaptiqTrial.lead_id == Lead.id)
            .order_by(AdaptiqTrial.trial_start.desc())
            .limit(limit)
        )
        rows = result.all()
        return [
            {
                "id": str(t.id), "lead": l.ig_handle, "name": l.name,
                "trial_start": t.trial_start.isoformat(),
                "trial_end": t.trial_end.isoformat(),
                "converted": t.converted_at is not None,
                "plan": t.plan,
                "improvement_pct": t.improvement_pct,
                "day1_sent": bool(t.day1_sent), "day3_sent": bool(t.day3_sent),
                "day5_sent": bool(t.day5_sent), "day7_sent": bool(t.day7_sent),
                "webinar_attended": bool(t.webinar_attended),
                "demo_booked": bool(t.demo_booked),
                "payment_initiated": bool(t.payment_initiated),
            }
            for t, l in rows
        ]


@app.get("/revenue")
async def get_revenue(days: int = 30):
    """Real revenue from admissions table + Adaptiq conversions."""
    from sqlalchemy import text
    from src.database import AsyncSessionLocal
    from datetime import timezone, timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        try:
            r = await db.execute(text("""
                SELECT course_type, COUNT(*) as count, SUM(fee_paid) as total
                FROM admissions WHERE payment_date >= :since
                GROUP BY course_type ORDER BY total DESC
            """), {"since": since})
            admissions = [dict(row._mapping) for row in r.fetchall()]
            r2 = await db.execute(text("SELECT SUM(fee_paid) FROM admissions WHERE payment_date >= :since"), {"since": since})
            topper_total = r2.scalar() or 0
        except Exception:
            admissions = []; topper_total = 0
        try:
            r3 = await db.execute(text("""
                SELECT plan, COUNT(*) as count FROM adaptiq_trials
                WHERE converted_at >= :since GROUP BY plan
            """), {"since": since})
            adaptiq_plans = [dict(row._mapping) for row in r3.fetchall()]
            adaptiq_total = sum(
                (1999 if "annual" in (p.get("plan") or "").lower() else 299) * p["count"]
                for p in adaptiq_plans
            )
        except Exception:
            adaptiq_plans = []; adaptiq_total = 0
    return {
        "period_days": days,
        "topper_ias": {"total": topper_total, "breakdown": admissions},
        "adaptiq": {"total": adaptiq_total, "plans": adaptiq_plans},
        "combined_total": topper_total + adaptiq_total,
    }


class AdmissionRequest(BaseModel):
    student_name: str
    course_type: str = "full_batch"
    fee_paid: int
    source: str = "direct"
    lead_id: str = ""
    notes: str = ""


@app.post("/admissions")
async def record_admission(body: AdmissionRequest):
    """Record a real admission for revenue tracking."""
    from src.database import AsyncSessionLocal
    from src.models import Admission
    import uuid
    async with AsyncSessionLocal() as db:
        admission = Admission(
            id=uuid.uuid4(),
            student_name=body.student_name,
            course_type=body.course_type,
            fee_paid=body.fee_paid,
            source=body.source,
            lead_id=uuid.UUID(body.lead_id) if body.lead_id else None,
            notes=body.notes or None,
        )
        db.add(admission)
        await db.commit()
        logger.info(f"[Revenue] Admission recorded: {body.student_name} ₹{body.fee_paid}")
    return {"status": "ok", "id": str(admission.id)}


@app.get("/admissions")
async def list_admissions(limit: int = 20):
    from sqlalchemy import text
    from src.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            r = await db.execute(text(
                "SELECT id::text,student_name,course_type,fee_paid,source,payment_date::text FROM admissions ORDER BY payment_date DESC LIMIT :l"
            ), {"l": limit})
            return [dict(row._mapping) for row in r.fetchall()]
        except Exception:
            return []


@app.post("/analytics/sync-insights")
async def sync_insights():
    """Pull Instagram Insights for all posted posts."""
    from src.tools.analytics_tool import sync_post_analytics
    updated = await sync_post_analytics()
    return {"updated": updated}


@app.post("/content/test-reel")
async def test_reel(topic: str = "3 Mistakes UPSC Toppers Never Make"):
    """Generate a test reel video and return the R2 URL."""
    import traceback
    errors = []

    # Step 1: check imageio
    try:
        import imageio
        errors.append(f"imageio ok: {imageio.__version__}")
    except Exception as e:
        errors.append(f"imageio FAILED: {e}")
        return {"status": "error", "errors": errors}

    # Step 2: check ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        errors.append(f"ffmpeg ok: {ffmpeg_path}")
    except Exception as e:
        errors.append(f"ffmpeg FAILED: {e}")

    # Step 3: try creating a simple test video with ffmpeg subprocess
    try:
        import tempfile, subprocess, os
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_img:
            img_path = tmp_img.name
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
            vid_path = tmp_vid.name
        # Create a test image
        from PIL import Image
        img = Image.new("RGB", (1080, 1920), (7, 8, 15))
        img.save(img_path, "JPEG")
        # Use ffmpeg to create a 1-second video from the image
        cmd = [ffmpeg_bin, "-y", "-loop", "1", "-i", img_path,
               "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", vid_path]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        size = os.path.getsize(vid_path)
        os.unlink(img_path)
        os.unlink(vid_path)
        errors.append(f"test video ok: {size} bytes")
    except Exception as e:
        errors.append(f"test video FAILED: {e}\n{traceback.format_exc()[-300:]}")
        return {"status": "error", "errors": errors}

    # Step 4: full reel
    try:
        from src.tools.reel_video_creator import create_reel_video
        url = await create_reel_video(
            hook="Stop making these UPSC mistakes!",
            value_points=["Mistake 1: Ignoring NCERT", "Mistake 2: Skipping current affairs", "Mistake 3: No answer writing"],
            cta="Follow TOPPER IAS",
            topic=topic,
            duration_seconds=15,
        )
        return {"status": "ok" if url else "failed", "video_url": url, "debug": errors}
    except Exception as e:
        import traceback as tb
        errors.append(f"reel FAILED: {e}\n{tb.format_exc()[-500:]}")
        return {"status": "error", "errors": errors, "debug": errors}


@app.post("/content/generate-reel-post")
async def generate_reel_post(topic: str = "3 Mistakes UPSC Toppers Never Make"):
    """Generate a reel script post and save to DB with platform=reel."""
    import uuid as _uuid
    from datetime import timezone, timedelta
    from src.database import AsyncSessionLocal
    from src.models import Post, Platform, PostStatus
    from src.agents.reel_script_agent import run_reel_script_agent
    from src.tools.visual_tool import generate_image
    from src.agents.visual_creator_agent import run_visual_creator_agent

    try:
        script = run_reel_script_agent(topic=topic, tone="motivational")
        caption = (
            f"🎬 {script.hook}\n\n"
            + "\n".join(f"✅ {pt}" for pt in script.value_points)
            + f"\n\n👉 {script.cta}\n\n"
            "#UPSC #IAS #TopperIAS #UPSCPreparation #CivilServices "
            "#IASAspirant #UPSCMotivation #StudyTips #Adaptiq #ReelScript"
        )
        visual = run_visual_creator_agent(caption=script.hook, topic=topic)
        image_url = await generate_image(prompt=visual.image_prompt, topic=topic)
        now = datetime.now(timezone.utc)
        scheduled = now.replace(hour=19, minute=30, second=0, microsecond=0)
        if now > scheduled:
            scheduled = scheduled + timedelta(days=1)
        async with AsyncSessionLocal() as db:
            post = Post(
                id=_uuid.uuid4(), platform=Platform.reel,
                caption_a=caption[:2200], caption_b=script.caption,
                image_url=image_url, scheduled_at=scheduled,
                status=PostStatus.pending,
            )
            db.add(post)
            await db.commit()
            return {"status": "ok", "post_id": str(post.id), "hook": script.hook, "platform": "reel"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


@app.post("/content/generate-shorts")
async def generate_shorts(topic: str = "UPSC Preparation Tips"):
    """Generate a YouTube Shorts package for a topic."""
    from src.tools.youtube_tool import generate_shorts_package
    package = await generate_shorts_package(topic)
    return package


@app.post("/content/generate-carousel")
async def generate_carousel_endpoint(topic: str = "UPSC Tips", slides: int = 5):
    """Generate a branded carousel using Canva tool."""
    from src.agents.content_writer_agent import run_content_writer_agent
    from src.tools.canva_tool import generate_carousel
    content = run_content_writer_agent(topic=topic, tone="educational")
    slide_data = [
        {"title": f"Tip {i+1}", "body": content.caption_a[i*60:(i+1)*60]}
        for i in range(min(slides, 5))
    ]
    urls = await generate_carousel(slide_data, topic=topic)
    return {"topic": topic, "slides": len(urls), "urls": urls}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

@app.get("/admin/debug")
async def debug():
    import os, ssl
    redis_url = os.getenv("REDIS_URL", "NOT SET")
    redis_ok = False
    queue_len = 0
    redis_version = ""
    try:
        import redis as rl
        redis_version = rl.__version__
        if redis_url.startswith("rediss://"):
            import re
            url_fixed = re.sub(r'ssl_cert_reqs=CERT_NONE', 'ssl_cert_reqs=none', redis_url, flags=re.IGNORECASE)
            if "ssl_cert_reqs" not in url_fixed:
                url_fixed = url_fixed + ("&" if "?" in url_fixed else "?") + "ssl_cert_reqs=none"
            try:
                r = rl.from_url(url_fixed, decode_responses=True)
                r.ping()
                redis_ok = True
            except Exception as e1:
                queue_len = f"failed: {str(e1)[:120]}"
        else:
            r = rl.from_url(redis_url, decode_responses=True)
            r.ping()
            redis_ok = True
        if redis_ok:
            queue_len = r.llen("celery")
    except Exception as e:
        queue_len = str(e)
    return {
        "redis_url_full": redis_url,
        "redis_ok": redis_ok,
        "redis_version": redis_version,
        "celery_queue_length": queue_len,
        "groq_key_set": bool(os.getenv("GROQ_API_KEY")),
        "db_url_set": bool(os.getenv("DATABASE_URL")),
    }


@app.get("/admin/test-r2")
async def test_r2():
    """Test R2 upload with a small test file."""
    try:
        from src.tools.storage_tool import upload_media
        test_bytes = b"BrandIQ R2 test " + datetime.now().isoformat().encode()
        url = upload_media(test_bytes, "test.txt", content_type="text/plain")
        return {"status": "ok", "url": url}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/admin/fix-post-images")
async def fix_post_images():
    """Replace placeholder image URLs with a real R2-hosted image."""
    from sqlalchemy import text
    from src.database import AsyncSessionLocal
    from src.tools.canva_tool import create_quote_card, upload_canva_image
    from src.tools.storage_tool import generate_filename

    # Generate a real branded image
    image_bytes = create_quote_card(
        headline="UPSC Preparation Tips",
        subtext="Daily insights by TOPPER IAS",
        watermark="TOPPER IAS",
    )
    filename = generate_filename("topper-ias-default", content_type="post")
    image_url = await upload_canva_image(image_bytes, filename)

    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "UPDATE posts SET image_url = :url WHERE image_url LIKE '%placeholder%' OR image_url LIKE '%via.placeholder%' RETURNING id::text"
        ), {"url": image_url})
        updated = [row[0] for row in result.fetchall()]
        await db.commit()

    return {"updated": len(updated), "image_url": image_url}


@app.post("/admin/backfill-ig-ids")
async def backfill_ig_ids():
    """Backfill Instagram post IDs for already-published posts."""
    from sqlalchemy import text
    from src.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Add columns if missing
        for col in ["ig_post_id", "fb_post_id"]:
            try:
                await db.execute(text(f"ALTER TABLE posts ADD COLUMN IF NOT EXISTS {col} VARCHAR"))
                await db.commit()
            except Exception:
                await db.rollback()
        # Backfill known IDs
        known = [
            ("45232814-af48-477d-ab04-14a68ce1d660", "17960749851111337"),
            ("36603817-d063-4559-83b0-4222fea1acd4", "18127081978582055"),
        ]
        updated = 0
        for post_id, ig_id in known:
            try:
                result = await db.execute(text(
                    "UPDATE posts SET ig_post_id = :ig WHERE id = :pid::uuid AND ig_post_id IS NULL"
                ), {"ig": ig_id, "pid": post_id})
                if result.rowcount > 0:
                    updated += 1
            except Exception as e:
                await db.rollback()
        await db.commit()
    return {"updated": updated, "columns_added": ["ig_post_id", "fb_post_id"]}


@app.post("/admin/reschedule-posts")
async def reschedule_posts():
    """Move all past-dated pending posts to today 7:30 PM IST."""
    from sqlalchemy import text
    from src.database import AsyncSessionLocal
    from datetime import timezone, timedelta
    now = datetime.now(timezone.utc)
    today_730pm = now.replace(hour=14, minute=0, second=0, microsecond=0)  # 14:00 UTC = 19:30 IST
    if now > today_730pm:
        today_730pm = today_730pm + timedelta(days=1)
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "UPDATE posts SET scheduled_at = :t WHERE scheduled_at < NOW() AND status = 'pending' RETURNING id::text"
        ), {"t": today_730pm})
        updated = [row[0] for row in result.fetchall()]
        await db.commit()
    return {"updated": len(updated), "new_time": today_730pm.isoformat()}


@app.post("/admin/create-tables")
async def create_tables():
    """Create all missing tables using SQLAlchemy metadata."""
    from src.database import engine, Base
    import src.models  # noqa — register all models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return {"status": "ok", "message": "All tables created"}


@app.post("/admin/run-migrations")
async def run_migrations():
    """Run alembic migrations manually."""
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }


@app.post("/admin/fix-enums")
async def fix_enums():
    """Create missing enum types directly in the DB."""
    import asyncpg
    db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    enums = [
        ("leadstatus",     "hot,warm,cold,opted_out"),
        ("leadsource",     "instagram_dm,instagram_comment,telegram"),
        ("platform",       "instagram,telegram,reel,whatsapp,story,carousel,facebook"),
        ("poststatus",     "pending,approved,posted,failed"),
        ("jobstatus",      "pending,running,success,failed,dead_letter"),
        ("sequencestatus", "sent,failed,opted_out"),
    ]
    results = {}
    conn = await asyncpg.connect(db_url)
    try:
        for name, values in enums:
            vals = ",".join(f"'{v}'" for v in values.split(","))
            try:
                await conn.execute(f"CREATE TYPE {name} AS ENUM ({vals})")
                results[name] = "created"
            except Exception as e:
                # Try adding missing values to existing enum
                if "already exists" in str(e):
                    for v in values.split(","):
                        try:
                            await conn.execute(f"ALTER TYPE {name} ADD VALUE IF NOT EXISTS '{v}'")
                        except Exception:
                            pass
                    results[name] = "updated"
                else:
                    results[name] = f"error: {str(e)[:60]}"
    finally:
        await conn.close()
    return results
@app.get("/webhook/instagram")
async def instagram_webhook_verify(
    request: Request,
):
    """Meta calls this GET endpoint to verify the webhook URL.
    Query params use dots (hub.mode, hub.verify_token, hub.challenge)
    which FastAPI can't map directly — read from request.query_params.
    """
    from src.tools.webhook_handler import verify_webhook
    from fastapi.responses import PlainTextResponse
    from fastapi import HTTPException

    params = request.query_params
    hub_mode     = params.get("hub.mode", "")
    hub_token    = params.get("hub.verify_token", "")
    hub_challenge = params.get("hub.challenge", "")

    logger.info(f"[Webhook] Verification attempt: mode={hub_mode}, token_match={hub_token == 'brandiq_webhook_secret_2024'}")

    challenge = verify_webhook(mode=hub_mode, token=hub_token, challenge=hub_challenge)
    if challenge:
        logger.info("[Webhook] Verification successful")
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@app.post("/webhook/instagram")
async def instagram_webhook(request: Request):
    """Meta posts DM and comment events here."""
    from src.tools.webhook_handler import handle_instagram_event
    payload = await request.json()
    result = await handle_instagram_event(payload)
    return JSONResponse(status_code=200, content=result)
