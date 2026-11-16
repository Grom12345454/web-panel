"""Prevent read receipt buttons from being disabled by the observer CSS guard.

A CSS-only regression previously blocked the click before the allowed POST
could reach the server. No Flask installation is needed for these checks.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE_CSS = ROOT / 'static/css/site.bundle.css'
SITE_JS = ROOT / 'static/js/site.bundle.js'


class ObserverReadCssRegressionTests(unittest.TestCase):
    def test_read_receipts_are_explicit_exception_to_disabled_post_forms(self):
        for css in (
            ROOT / 'frontend/assets/styles/portal/ui-polish-v8.css',
            ROOT / 'frontend/assets/styles/portal/ui-polish-v9.css',
            ROOT / 'static/css/site.bundle.css',
        ):
            with self.subTest(file=css.name):
                contents = css.read_text(encoding='utf-8')
                self.assertIn(':not([data-notification-read]):not([data-notification-read-all])', contents)
        bundle = SITE_CSS.read_text(encoding='utf-8')
        self.assertIn('body.role-observer form[data-notification-read]', bundle)
        self.assertIn('body.role-observer form[data-notification-read-all]', bundle)
        self.assertIn('pointer-events: auto !important', bundle)
        template = (ROOT / 'frontend/templates/system/notifications.html').read_text(encoding='utf-8')
        self.assertIn('method="post" data-notification-read ', template)
        self.assertIn('method="post" data-notification-read-all ', template)

    def test_real_chromium_click_single_and_all_without_unlocking_admin_forms(self):
        executable = shutil.which('chromium') or shutil.which('chromium-browser')
        if not executable:
            self.skipTest('Chromium is not installed')
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright is not installed')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=executable,
                                         args=['--no-sandbox'])
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.set_content('''<!DOCTYPE html><html><body class="uc-body role-observer">
                  <span data-notification-count>2</span>
                  <div data-notifications-center>
                    <article data-notification-item class="alert-item is-unread">
                      <form method="post" data-notification-read action="/notifications/1/read">
                        <input name="csrf_token" value="fake-for-browser-test">
                        <button type="submit">✓ Отметить прочитанным</button></form>
                    </article>
                    <article data-notification-item class="alert-item is-unread">
                      <form method="post" data-notification-read action="/notifications/2/read">
                        <button type="submit">✓ Отметить прочитанным</button></form>
                    </article>
                  </div>
                  <form method="post" data-notification-read-all action="/notifications/read-all">
                    <button type="submit">Отметить показанные как прочитанные</button></form>
                  <form method="post" id="admin-write"><button type="submit">Изменить настройки</button></form>
                  <span class="alerts-stat">2 непрочитанных</span>
                  <div data-notification-status hidden></div>
                </body></html>''')
                # Mock the transport ONLY. This is an actual click/hit-testing test
                # against the shipped stylesheet and JavaScript bundle.
                page.evaluate('''window.testReadCalls = 0;
                  window.fetch = async (url, options = {}) => {
                    if (options.method === 'POST') {
                      window.testReadCalls++;
                      return {ok:true, redirected:false, json:async () =>
                        ({ok:true, marked:1, unread: 2-window.testReadCalls})};
                    }
                    return {ok:true,json:async () => ({ok:true,unread:2})};
                  };''')
                page.add_style_tag(content=SITE_CSS.read_text(encoding='utf-8'))
                page.add_script_tag(content=SITE_JS.read_text(encoding='utf-8'))
                for selector in ('form[data-notification-read]', 'form[data-notification-read-all]'):
                    self.assertEqual(page.locator(selector).first.evaluate(
                        '(el) => getComputedStyle(el).pointerEvents'), 'auto')
                self.assertEqual(page.locator('#admin-write').evaluate(
                    '(el) => getComputedStyle(el).pointerEvents'), 'none')
                page.locator('form[data-notification-read] button').first.click(timeout=5000)
                page.wait_for_function("document.querySelectorAll('.alert-read-confirmation').length === 1")
                page.locator('form[data-notification-read-all] button').click(timeout=5000)
                page.wait_for_function("document.querySelectorAll('.alert-read-confirmation').length === 2")
                self.assertEqual(page.evaluate('window.testReadCalls'), 2)
                self.assertEqual(page.locator('.alerts-stat').inner_text(), '0 непрочитанных')
                self.assertFalse(errors)
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
