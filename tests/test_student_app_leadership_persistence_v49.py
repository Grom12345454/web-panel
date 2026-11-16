from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_leadership_directory_is_not_lost_when_live_sync_replaces_profile_state():
    source = (ROOT / "frontend/assets/scripts/student/student_app.js").read_text("utf-8")
    bundle = (ROOT / "static/js/student-app.bundle.js").read_text("utf-8")

    # Directory data is sourced independently of /api/me and must survive state=fresh.
    assert "let leadershipDirectoryCache=null" in source
    assert "Array.isArray(leadershipDirectoryCache)" in source
    assert "const people=Array.isArray(leadershipDirectoryCache)" in source
    assert "leadershipDirectoryCache=d.cards" in source
    assert "leadershipDirectoryLoadedAt=Date.now()" in source
    assert "leadershipDirectoryCache=d.cards" in bundle
    assert "const people=Array.isArray(leadershipDirectoryCache)" in bundle


def test_transient_directory_response_does_not_clear_previously_loaded_roster():
    source = (ROOT / "frontend/assets/scripts/student/student_app.js").read_text("utf-8")
    fetcher = source.split("async function fetchLeadershipDirectory", 1)[1].split("function leader()", 1)[0]
    assert "if(Array.isArray(d.cards))" in fetcher
    assert "leadershipDirectoryCache=d.cards" in fetcher
    # No empty fallback like d.cards||[] may replace known-good roster after a malformed response.
    assert "state.leadership_directory=d.cards||[]" not in fetcher
    assert "finally{leadershipDirectoryBusy=false;}" in fetcher
    assert "Date.now()-leadershipDirectoryLoadedAt>=60000" in source
    assert "fetchLeadershipDirectory({silent:true})" in source
