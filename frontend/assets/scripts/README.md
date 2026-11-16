# JavaScript source map

- `shared/`: reusable page lifecycle and motion helpers.
- `portal/`: staff portal interactions, theme designer, calendar, notifications, orders and journal UI.
- `student/`: Student App state, routes, rendering and account features.

Keep server-side authorization in `backend/app`; hiding a button is not authorization. Page-specific modules must exit cleanly when their root element is absent. Pause timers and animation work when the page is hidden, and respect `prefers-reduced-motion`.

Scripts loaded individually by legacy or feature templates belong in `frontend/assets/standalone/js/`; the build publishes them to their current `/static/js/...` URLs. Do not author or patch files directly under `static/`.
