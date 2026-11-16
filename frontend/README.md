# Frontend architecture

Canonical frontend source is stored in this directory. Flask continues to serve generated/public assets from the root `static/` directory so existing URLs remain stable (`/static/css/...`, `/static/js/...`).

## Structure

- `templates/`: Jinja templates, grouped by feature (`auth`, `dashboard`, `student`, `staff`, `calendar`, `orders`, etc.). Templates own markup and semantic structure; reusable layout belongs in `shared/`.
- `assets/styles/shared/`: design tokens, typography, global effects, shared components and accessibility behavior.
- `assets/styles/portal/`: general staff portal shell, navigation, dashboard and page styles.
- `assets/styles/staff/`: admin console, staff tools, monitoring and audit UI.
- `assets/styles/student/`: Student App-specific pages, responsive layout and components.
- `assets/scripts/shared/`: cross-product runtime helpers and motion lifecycle.
- `assets/scripts/portal/`: staff portal interactions and APIs.
- `assets/scripts/student/`: Student App state, API calls and UI interactions.
- `assets/standalone/css/`: individual stylesheets loaded directly by feature templates.
- `assets/standalone/js/`: individual scripts loaded directly by feature templates.
- `scripts/build_assets.py`: explicit bundle entrypoints, cascade order and publishing of standalone files.

## CSS conventions

1. Add a new rule to the owning feature file; use `shared/` only when at least two products genuinely share it.
2. Prefer component/page names (`student-profile-card.css`, `staff-audit-log.css`) over release-number names for new work. Keep historical filenames unchanged until a separately tested consolidation.
3. Group rules inside each file as: tokens/variables, base states, layout, components, interaction states, responsive rules, reduced-motion/forced-colors.
4. Avoid appending broad global selectors to fix one page. Scope page rules to a body/page root or component namespace.
5. Keep keyboard focus, reduced-motion and contrast states in the same component stylesheet.
6. Bundle order is deliberate and defined in `scripts/build_assets.py`; source files are ordered by foundation, product, feature and final theme layers.

## JavaScript conventions

- Keep one concern per module. Shared modules must not depend on page-specific DOM nodes.
- Guard page-specific initialisation with a root element/data-page check.
- Prefer `addEventListener`, abortable listeners and explicit teardown for timers/observers.
- Use `fetch` wrappers from the feature module, handle non-2xx responses and keep auth/permission decisions on the server.
- Do not add pointer-following effects or perpetual animation loops without visibility/reduced-motion guards.

## Build

Run `python scripts/build_assets.py` from the repository root. Edit only `frontend/assets/`; output is written to root `static/`. Existing URL paths remain unchanged. The `static/` folder is the public deployment target, not a source-code directory.

## Mobile device compatibility

Student App responsive rules live in `assets/styles/student/student-responsive-2026.css` and the final cross-generation compatibility layer `assets/styles/student/student-mobile-compat-2026.css`. Runtime viewport, OS family, WebView and keyboard capability handling lives at the top of `assets/scripts/student/student_app.js`. See the repository-level `MOBILE_DEVICE_SUPPORT_2026.md` for the tested viewport matrix and the explicit legacy-engine limits.
