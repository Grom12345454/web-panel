from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reaction_updates_only_reaction_strip_and_targets_message_article():
    script = (ROOT / "static/js/staff-messenger.js").read_text(encoding="utf-8")
    assert "reaction.closest('article.messenger-message')" in script
    assert "strip.innerHTML = renderReactions(updated)" in script
    assert "item.outerHTML = renderMessage(updated)" not in script


def test_reaction_api_returns_updated_message_aggregate():
    source = (ROOT / "backend/app/services/staff_messenger.py").read_text(encoding="utf-8")
    assert '"message": _message_payload(message, current_user)' in source
