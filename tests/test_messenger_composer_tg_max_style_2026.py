from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_composer_uses_accessible_paperclip_and_icon_send_controls():
    template = read("frontend/templates/messenger/staff_messenger.html")
    assert 'id="messenger-attach-trigger"' in template
    assert 'aria-label="Прикрепить файл"' in template
    assert 'aria-label="Отправить сообщение"' in template
    assert 'id="messenger-message-input"' in template
    assert '<svg viewBox="0 0 24 24"' in template
    assert 'placeholder="Написать сообщение…"' in template


def test_native_file_input_is_hidden_and_file_preview_remains_available():
    template = read("frontend/templates/messenger/staff_messenger.html")
    css = read("static/css/messenger-workspace.css")
    script = read("static/js/staff-messenger.js")
    assert 'id="messenger-attachments"' in template
    assert 'id="messenger-draft-attachments"' in template
    assert 'body.messenger-standalone #messenger-attachments' in css
    assert 'display: none !important' in css
    assert "data-remove-draft-file" in script
    assert "messenger-attach-trigger" in script


def test_composer_keyboard_shortcuts_and_drag_drop_are_preserved():
    script = read("static/js/staff-messenger.js")
    assert "event.shiftKey" in script
    assert "event.isComposing" in script
    assert "dataTransfer?.files" in script
    assert "composer.requestSubmit" in script
