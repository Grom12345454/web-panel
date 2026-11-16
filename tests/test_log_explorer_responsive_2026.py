"""Desktop/mobile regression for the admin investigation forms.

Uses the real, rendered form markup and the production CSS bundle without
starting Flask, opening a database or connecting to a messaging platform.
Browser checks are optional on machines without Chromium/Playwright.
"""
from pathlib import Path
import shutil

import pytest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'frontend/templates/activity/audit_log.html'
BOTS = ROOT / 'frontend/templates/activity/bot_journal.html'


def render_panel(kind='site'):
    path = SITE if kind == 'site' else BOTS
    source = path.read_text(encoding='utf-8')
    marker = '<div class="log-explorer-filter-panel"' if kind == 'site' else '<div class="log-explorer-filter-panel log-explorer-filter-panel--bots"'
    start = source.index(marker)
    if kind == 'site':
        end = source.index('\n    </section>', start)
    else:
        end = source.index('\n  </section>', start)
    excerpt = source[start:end]
    filters = dict(q='', level='all', method='', actor='', start='', end='',
                   kind='', platform='', status='')
    markup = Environment(autoescape=True).from_string(excerpt).render(
        view='http', filters=filters,
        platform_names={'telegram': 'Telegram', 'vk': 'VK', 'max': 'MAX'},
        kind_names={'incoming': 'Входящие', 'outgoing': 'Исходящие'},
        status_names={'success': 'Успешно', 'error': 'Ошибка'},
        url_for=lambda endpoint, **params: '/mock/' + endpoint.split('.')[-1]
    )
    css = (ROOT / 'static/css/site.bundle.css').read_text(encoding='utf-8')
    if kind == 'bots':
        css += '\n' + (ROOT / 'static/css/bot-journal.css').read_text(encoding='utf-8')
    return ('<!doctype html><html lang="ru"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>' + css + '\n@media(max-width:900px){.preview-sidebar{display:none}'
            '.preview-main{padding:12px!important}}</style>'
            '<body class="uc-body" style="background:#07111f;color:#e8f4ff;font:13px system-ui;margin:0">'
            '<div style="display:flex;min-height:100vh">'
            '<aside class="preview-sidebar" style="width:230px;flex:0 0 230px;background:#0d1b2e"></aside>'
            '<main class="preview-main" style="flex:1;min-width:0;padding:25px">'
            '<div class="pro-log-workspace"><section class="pro-log-investigate">'
            '<h2>Журнал · поиск</h2>' + markup + '</section></div>'
            '</main></div></body></html>')


def test_isolated_filters_not_nested_inside_legacy_audit_toolbar():
    audit = SITE.read_text('utf-8')
    bot = BOTS.read_text('utf-8')
    assert 'class="audit-toolbar audit-operations-v5"' not in audit
    assert 'class="audit-operations-form"' not in audit
    assert 'log-explorer-filter-panel' in audit and 'log-explorer-filter-panel--bots' in bot
    assert 'name="view"' in audit and 'name="focus" value="events"' in bot
    assert 'log-explorer-advanced' in audit and 'log-explorer-advanced' in bot
    assert 'name="q"' in audit and 'name="q"' in bot
    assert 'name="start"' in audit and 'name="end"' in bot
    assert '.uc-body .log-explorer-primary' in (ROOT / 'static/css/site.bundle.css').read_text('utf-8')


def test_real_chromium_filter_widths_on_desktop_tablet_and_mobile():
    playwright = pytest.importorskip('playwright.sync_api')
    browser_path = shutil.which('chromium') or shutil.which('chromium-browser')
    if not browser_path:
        pytest.skip('Chromium not available')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=browser_path,
                                    args=['--no-sandbox'])
        try:
            for kind in ('site', 'bots'):
                html = render_panel(kind)
                for width in (1622, 1280, 1024, 768, 480, 390):
                    page = browser.new_page(viewport={'width': width, 'height': 900})
                    try:
                        page.set_content(html, wait_until='load')
                        selector = '#audit-query' if kind == 'site' else '#bot-journal-query'
                        input_width = page.locator(selector).bounding_box()['width']
                        assert input_width >= 180, (kind, width, input_width)
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), (kind, width)
                        primary = page.locator('.log-explorer-primary').bounding_box()
                        assert primary['width'] > 250, (kind, width, primary)
                        assert page.locator('.log-explorer-advanced').count() == 1
                        assert page.locator('.log-explorer-quick a').count() >= 1
                    finally:
                        page.close()
        finally:
            browser.close()
