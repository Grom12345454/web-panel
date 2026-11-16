# Styles source map

`shared/` = cross-product foundations and reusable visual systems. `portal/` = common staff workspace and page layouts. `staff/` = administration, journals, management tools and runtime health. `student/` = Student App only.

Use small, feature-owned files. Shared design tokens belong in `shared/galaxy-tokens.css`; don't duplicate theme variables in each product. Keep responsive behavior and `prefers-reduced-motion` near the affected component. The canonical import/cascade order is `SITE_CSS` / `STUDENT_CSS` in `scripts/build_assets.py`; do not reorder those lists without reviewing both product bundles.

The historical filenames (including `vXX` suffixes) are retained to prevent accidental regressions. New styles should use stable feature names rather than a new version number for every correction. Styles loaded individually by a legacy/feature template belong in `frontend/assets/standalone/css/`; the build copies them to their existing public URL in `static/css/`.

## Consolidated portal polish and header

`portal/ui-polish.css` is the single source of truth for the portal polish layer. The old v5–v8 public copies are not published. The v9 URL remains as a tiny `@import` compatibility alias only; it contains no duplicate declarations. `portal/admin-header-fix.css` is the final site-bundle layer and styles the admin top bar independently of historical `data-ui-version` gates.
