# Standalone frontend assets

These files are maintained in the frontend source tree but are loaded directly by
individual Jinja templates instead of being concatenated into the portal or Student
App bundles. `scripts/build_assets.py` copies them into `static/css/` and `static/js/`
while preserving their current public URLs.

- `css/`: stylesheets for authentication, bot journal, staff management and other
  feature-specific pages that still use individual `<link>` tags.
- `js/`: page scripts for OTP, login security, runtime status, bot journal and other
  feature-specific pages that still use individual `<script>` tags.

Edit files here, never under `static/`. Run `python scripts/build_assets.py` after
changes.
