import os
import pytest
from unittest.mock import MagicMock, patch

# Set dummy env vars before any imports
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("META_VERIFY_TOKEN", "brandiq_webhook_secret_2024")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


# ---------------------------------------------------------------------------
# test_content_writer_agent
# ---------------------------------------------------------------------------

def test_content_writer_agent():
    mock_response = MagicMock()
    mock_response.content = """{
        "caption_a": "Master UPSC Prelims with these 5 proven strategies that toppers swear by 📚",
        "caption_b": "Are you preparing for UPSC Prelims? Here's what actually works in 2024 🎯",
        "hashtags": ["upsc", "ias", "upscpreparation", "iasaspirant", "upsc2024",
                     "civilservices", "upscmotivation", "iascoaching", "topperIAS",
                     "upscstrategy", "prelims", "upscexam", "iasexam", "studymotivation", "adaptiq"],
        "best_post_time": "7:00 AM IST"
    }"""

    with patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke", return_value=mock_response):
        from src.agents.content_writer_agent import run_content_writer_agent, PostContent
        result = run_content_writer_agent("UPSC Prelims strategy", "motivational")

    assert isinstance(result, PostContent)
    assert len(result.caption_a) > 0
    assert len(result.hashtags) == 15


# ---------------------------------------------------------------------------
# test_lead_capture_agent
# ---------------------------------------------------------------------------

def test_lead_capture_agent():
    mock_response = MagicMock()
    mock_response.content = """{
        "ig_handle": "test_user_123",
        "status": "hot",
        "intent_keywords_found": ["fees", "batch"],
        "auto_reply_message": "Hi! Thanks for reaching out to TOPPER IAS. Our next batch starts soon — DM us for fee details!",
        "should_notify_admin": true
    }"""

    with patch("langchain_google_genai.ChatGoogleGenerativeAI.invoke", return_value=mock_response):
        from src.agents.lead_capture_agent import run_lead_capture_agent, LeadScore
        result = run_lead_capture_agent("what are the fees for batch?", "test_user_123")

    assert isinstance(result, LeadScore)
    assert result.status == "hot"
    assert "fees" in result.intent_keywords_found


# ---------------------------------------------------------------------------
# test_webhook_verify
# ---------------------------------------------------------------------------

def test_webhook_verify():
    from src.tools.webhook_handler import verify_webhook

    # Valid token
    result = verify_webhook("subscribe", "brandiq_webhook_secret_2024", "test_challenge")
    assert result == "test_challenge"

    # Wrong token
    result = verify_webhook("subscribe", "wrong_token", "test_challenge")
    assert result is None

    # Wrong mode
    result = verify_webhook("unsubscribe", "brandiq_webhook_secret_2024", "test_challenge")
    assert result is None
