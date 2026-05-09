import os

from loguru import logger

# Keywords that trigger the full event-driven nurture sequence.
INTENT_KEYWORDS = {
    "fees", "batch", "admission", "join", "cost", "price",
    "register", "enroll", "course", "classes", "timing",
    "schedule", "syllabus", "rank", "topper",
}


def verify_webhook(mode: str, token: str, challenge: str) -> str | None:
    verify_token = os.getenv("META_VERIFY_TOKEN", "")
    if mode == "subscribe" and token == verify_token:
        logger.info("[Webhook] Instagram webhook verified")
        return challenge
    logger.warning(f"[Webhook] Verification failed: mode={mode}, token_match={token == verify_token}")
    return None


async def handle_instagram_event(payload: dict) -> dict:
    """
    Entry point for all Instagram webhook events.

    DM flow (event-driven nurture):
      1. Receive DM
      2. Dispatch run_lead_crew_task (day=0) -> LeadCaptureAgent scores lead
         -> instant IG auto-reply queued
         -> Day 3/7/14 WhatsApp nurture scheduled via Celery ETA
      3. If intent keywords found -> admin Telegram alert (handled inside LeadCrew)

    Comment flow:
      Only triggers lead capture if intent keywords are present.
    """
    logger.info(f"[Webhook] Raw payload received: {payload}")

    from src.scheduler.tasks import run_lead_crew_task

    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        # ----------------------------------------------------------------
        # DM (messaging) — always triggers the full nurture pipeline
        # ----------------------------------------------------------------
        messages = value.get("messages", [])
        if messages:
            msg = messages[0]
            sender_id = msg.get("from", "")
            message_text = (
                msg.get("text", {}).get("body", "")
                if msg.get("type") == "text"
                else ""
            )

            logger.info(f"[Webhook] DM from {sender_id}: {message_text[:80]}")

            # Dispatch lead scoring + auto-reply + nurture scheduling
            run_lead_crew_task.delay(
                ig_handle=sender_id,
                message_text=message_text,
                day_number=0,
            )

            return {"status": "processed", "type": "dm", "sender": sender_id}

        # ----------------------------------------------------------------
        # Comment — only triggers nurture if intent keywords are present
        # ----------------------------------------------------------------
        comments = value.get("comments", [])
        if comments:
            comment = comments[0]
            sender_id = comment.get("from", {}).get("id", "")
            comment_text = comment.get("text", "")

            logger.info(f"[Webhook] Comment from {sender_id}: {comment_text[:80]}")

            text_lower = comment_text.lower()
            found = [kw for kw in INTENT_KEYWORDS if kw in text_lower]

            if found:
                logger.info(f"[Webhook] Intent keywords in comment: {found}")
                run_lead_crew_task.delay(
                    ig_handle=sender_id,
                    message_text=comment_text,
                    day_number=0,
                )
                return {"status": "processed", "type": "comment", "intent": found}

            return {"status": "ignored", "type": "comment", "reason": "no_intent"}

    except Exception as e:
        logger.error(f"[Webhook] Error handling Instagram event: {e}")
        return {"status": "error", "detail": str(e)}

    return {"status": "ignored", "type": "unknown"}
