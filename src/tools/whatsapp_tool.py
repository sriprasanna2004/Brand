import os
import uuid
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.models import Lead, LeadStatus, WhatsappSequence, SequenceStatus

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NURTURE_TEMPLATES = {
    1:  {"template_name": "brandiq_welcome",       "variables": ["{{lead_name}}", "{{batch_info}}"]},
    3:  {"template_name": "brandiq_adaptiq_trial", "variables": ["{{lead_name}}", "{{trial_link}}"]},
    7:  {"template_name": "brandiq_urgency",        "variables": ["{{lead_name}}", "{{seats_left}}"]},
    14: {"template_name": "brandiq_final_cta",      "variables": ["{{lead_name}}", "{{admission_link}}"]},
}


def _base_url() -> str:
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    return f"https://graph.facebook.com/v19.0/{phone_number_id}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('META_ACCESS_TOKEN', '')}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Core send helpers
# ---------------------------------------------------------------------------

async def send_template_message(phone: str, template_name: str, variables: list[str]) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": v} for v in variables],
                }
            ],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_base_url() + "/messages", json=payload, headers=_headers())
        resp.raise_for_status()
        logger.info(f"[WhatsApp] Template '{template_name}' sent to {phone}")
        return True
    except Exception as e:
        logger.error(f"[WhatsApp] Template send failed to {phone}: {e}")
        return False


async def send_text_message(phone: str, message: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message, "preview_url": False},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(_base_url() + "/messages", json=payload, headers=_headers())
        resp.raise_for_status()
        logger.info(f"[WhatsApp] Text message sent to {phone}")
        return True
    except Exception as e:
        logger.error(f"[WhatsApp] Text send failed to {phone}: {e}")
        return False


async def mark_as_read(message_id: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_base_url() + "/messages", json=payload, headers=_headers())
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"[WhatsApp] mark_as_read failed for {message_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Nurture sequence
# ---------------------------------------------------------------------------

async def send_nurture_message(lead_phone: str, lead_name: str, day_number: int) -> bool:
    from src.agents.lead_nurture_agent import run_lead_nurture_agent

    async with AsyncSessionLocal() as db:
        # Resolve lead
        lead = await db.scalar(select(Lead).where(Lead.phone == lead_phone))
        if not lead:
            logger.warning(f"[WhatsApp] No lead found for phone {lead_phone}")
            return False

        # Idempotency check
        already_sent = await db.scalar(
            select(WhatsappSequence).where(
                WhatsappSequence.lead_id == lead.id,
                WhatsappSequence.day_number == day_number,
            )
        )
        if already_sent:
            logger.info(f"[WhatsApp] Day {day_number} already sent for {lead_phone}, skipping")
            return False

        # Generate message via agent
        nurture = run_lead_nurture_agent(
            lead_name=lead_name,
            day_number=day_number,
            lead_status=lead.status.value,
        )

        # Resolve variables from agent output or fall back to template defaults
        variables = list(nurture.variables.values()) if nurture.variables else []

        success = await send_template_message(
            phone=lead_phone,
            template_name=nurture.template_name,
            variables=variables,
        )

        # Record sequence regardless of outcome
        seq = WhatsappSequence(
            id=uuid.uuid4(),
            lead_id=lead.id,
            day_number=day_number,
            template_name=nurture.template_name,
            status=SequenceStatus.sent if success else SequenceStatus.failed,
        )
        db.add(seq)
        await db.commit()

        return success


# ---------------------------------------------------------------------------
# Opt-out handler
# ---------------------------------------------------------------------------

async def handle_opt_out(phone: str) -> bool:
    async with AsyncSessionLocal() as db:
        lead = await db.scalar(select(Lead).where(Lead.phone == phone))
        if lead:
            lead.status = LeadStatus.opted_out
            lead.updated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"[WhatsApp] Opt-out recorded for phone={phone}, lead={lead.ig_handle}")
        else:
            logger.warning(f"[WhatsApp] Opt-out received but no lead found for phone={phone}")
    return True
