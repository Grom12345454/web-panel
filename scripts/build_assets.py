"""Build public frontend assets from canonical frontend sources.

Editable CSS/JS lives under ``frontend/assets``. ``static/`` contains only
files served by Flask and generated bundles. Run from the repository root:

    python scripts/build_assets.py
"""
from __future__ import annotations

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_CSS = ROOT / "static" / "css"
PUBLIC_JS = ROOT / "static" / "js"
ASSET_ROOT = ROOT / "frontend" / "assets"
STYLE_SOURCE = ASSET_ROOT / "styles"
SCRIPT_SOURCE = ASSET_ROOT / "scripts"
STANDALONE_CSS_SOURCE = ASSET_ROOT / "standalone" / "css"
STANDALONE_JS_SOURCE = ASSET_ROOT / "standalone" / "js"

# Standalone assets are linked directly by a small number of legacy or
# feature-specific templates. Their public URLs remain unchanged.
STANDALONE_CSS = [
    'admin-management.css',
    'app.css',
    'bot-journal.css',
    'institutional-redesign.css',
    'page-components-v9.css',
    'refresh-design.css',
    'student-app-redesign.css',
    'student-app-theme-designer.css',
    'student-app-v9.css',
    'student_app.css',
    'ui-polish-v9.css',
]

STANDALONE_JS = [
    'app.js',
    'bot-activity-live.js',
    'bot-journal.js',
    'login-security.js',
    'otp.js',
    'runtime-status.js',
    'site-sync.js',
    'space.js',
    'student-app-theme-designer.js',
    'student_app.js',
]

# The legacy portal bundle remains available for external/older templates.
LEGACY_PORTAL_CSS = [
    'app.css',
    'institutional-redesign.css',
    'refresh-design.css',
    'ui-polish.css',
]

# Portal shell and administration cascade. Order is intentional.
SITE_CSS = [
    # 01 · Shared design foundations
    'shared/galaxy-tokens.css',
    'shared/theme-change-motion-2026.css',
    'shared/theme-spectrum-v23.css',
    # 02 · Main portal / navigation and page layout
    'portal/app.css',
    'portal/institutional-redesign.css',
    'portal/refresh-design.css',
    'portal/ui-polish.css',
    'portal/student-app-theme-designer.css',
    'portal/page-components-v9.css',
    'portal/portal-2026.css',
    'portal/portal-modern-2026.css',
    'portal/home-purpose-2026.css',
    'portal/navigation-home-tuning.css',
    'portal/calendar.css',
    'portal/notifications.css',
    'portal/unified-ux.css',
    # 03 · Staff workspace and administration pages
    'staff/holiday-motion-2026.css',
    'staff/mission-design-v2.css',
    'staff/galaxy-portal-experience.css',
    'staff/galaxy-ui-release.css',
    'staff/galaxy-mission-control-20.css',
    'staff/mission-calendar-management.css',
    'staff/student-contacts-v5.css',
    'staff/journal-operations-v5.css',
    'shared/orbital-experience-v3.css',
    'staff/premium-console-2026.css',
    'staff/unified-logs-2026.css',
    'staff/ultra-console-2026.css',
    # 04 · Shared experience, account and motion layers
    'staff/professional-logs-2026.css',
    'staff/runtime-observability-2026.css',
    'shared/pro-workspace-2026.css',
    'shared/galaxy-depth-2026.css',
    'shared/galaxy-depth-plus-2026.css',
    'shared/galaxy-clarity-2026.css',
    'shared/staff-workspace-2026.css',
    'staff/staff-modal-directory-2026.css',
    'shared/login-refresh-2026.css',
    'shared/activity-chats-2026.css',
    'shared/event-direction-management.css',
    'shared/cosmos-world-2026.css',
    'shared/hero-smooth-performance-2026.css',
    'shared/professional-experience-2026.css',
    'shared/login-awwwards-2026.css',
    'shared/unified-space-2026.css',
    'portal/orders-archive.css',
    # 05 · Orders, monitoring and release layers
    'shared/immersive-emotion-v29.css',
    'staff/monitoring-layout-v30.css',
    'shared/kinetic-cinema-v31.css',
    'shared/overview-notifications-v32.css',
    'shared/login-zoom-stability-v34.css',
    'shared/login-single-panel-v36.css',
    'shared/holiday-visual-v40.css',
    'staff/admin-restricted-console-v42.css',
    'shared/observer-readonly-v46.css',
    'shared/holiday-atmosphere-v52.css',
    'shared/theme-smoke-v59.css',
    'shared/theme-smoke-v60.css',
    'shared/holiday-smoke-personalities-v61.css',
    'shared/performance-budget-2026.css',
    'shared/auth-panel-v59.css',
    'shared/neural-cinema-v61.css',
    'staff/user-activity-v61.css',
    'staff/admin-monitoring-v63.css',
    'staff/admin-shell-v64.css',
    'staff/admin-monitoring-v65.css',
    'staff/soc-monitoring-v66.css',
    # Consistent multi-select and single-select direction cards for forms.
    # Same premium admin shell and role-filtered navigation for all staff accounts.
    'shared/unified-role-shell-2026.css',
    # Staff dashboards reuse the exact admin layout with permission-scoped data.
    'staff/role-workspace-dashboard-2026.css',
    # Keep direction-picker rules last so they continue to win the cascade.
    'shared/direction-choice-ui.css',
    # Final common dashboard foundation: all roles share the admin design language.
    'shared/unified-dashboard-foundation-2026.css',
    # Final cross-role polish for all authenticated panel pages.
    'shared/role-panel-parity-2026.css',
    # Final, version-independent administration header layout.
    'portal/admin-header-fix.css',
    # Last lightweight pass for sidebar navigation responsiveness.
    'shared/sidebar-performance-v197.css',
    # Dedicated high-clarity styling for the system health and recovery console.
    'staff/runtime-health-console-v199.css',
    # Direct administrator actions for backup verification and recovery.
    'staff/runtime-recovery-actions-v112.css',
    # Advanced filters, readable trend charts and searchable/paginated tables.
    'portal/statistics-workspace-v1913.css',
    'portal/statistics-analytics-v1916.css',
    'portal/statistics-tables-v1917.css',
    'portal/statistics-ux-v1919.css',
    'portal/statistics-daily-ux-v1920.css',
]

SITE_JS = [
    # 00 · Detect constrained clients before starting visual renderers
    'shared/performance-budget-2026.js',
    # 01 · Portal shell and navigation
    'portal/app.js',
    'portal/space.js',
    'portal/site-sync.js',
    # 02 · Live data, theme and calendar
    'portal/bot-activity-live.js',
    'portal/student-app-theme-designer.js',
    'portal/theme-live-sync.js',
    'portal/announcement-preview.js',
    'portal/calendar.js',
    'portal/notifications.js',
    'portal/journal-ux.js',
    'portal/pro-workspace.js',
    # 03 · Shared immersive / page motion
    'shared/galaxy-depth-plus.js',
    'shared/cosmos-world-2026.js',
    'shared/page-entry-motion.js',
    'shared/admin-console-entry-v52.js',
    # 04 · Orders
    'portal/orders-archive.js',
    'portal/messenger-monitoring-v63.js',
    # Filters, sorting, pagination and CSV export for analytics tables.
    'portal/statistics-workspace-v1913.js',
]

STUDENT_CSS = [
    # 01 · Shared design foundations
    'shared/galaxy-tokens.css',
    'shared/theme-change-motion-2026.css',
    'shared/theme-spectrum-v23.css',
    # 02 · Student App core and structural layout
    'student/student_app.css',
    'student/student-app-redesign.css',
    'student/student-app-v9.css',
    'student/student-app-2026.css',
    'student/student-app-modern.css',
    'student/student-home-focus.css',
    # 03 · Student features and calendar
    'student/holiday-motion-2026.css',
    'student/command-center-unified.css',
    'student/galaxy-student-final.css',
    'student/galaxy-ui-release.css',
    'student/galaxy-mission-student-20.css',
    'student/unified-calendar-2026.css',
    'student/mission-list-v5.css',
    # 04 · Shared experience and presentation
    'shared/orbital-experience-v3.css',
    'student/premium-student-2026.css',
    'student/ultra-student-2026.css',
    'shared/pro-workspace-2026.css',
    'shared/galaxy-depth-2026.css',
    'shared/galaxy-depth-plus-2026.css',
    'shared/galaxy-clarity-2026.css',
    'student/department-announcements.css',
    # 05 · Announcements, account controls and ambient motion
    'student/account-links-fix.css',
    'student/student-gentle-motion.css',
    'shared/cosmos-world-2026.css',
    'shared/hero-smooth-performance-2026.css',
    'shared/professional-experience-2026.css',
    'shared/unified-space-2026.css',
    # 06 · Final theme and campus background layer
    'student/student-app-theme-spectrum-2026.css',
    'shared/immersive-emotion-v29.css',
    'shared/kinetic-cinema-v31.css',
    'shared/holiday-visual-v40.css',
    'student/campus-space-background-v48.css',
    'shared/holiday-atmosphere-v52.css',
    'student/student-responsive-2026.css',
    'student/student-mobile-compat-2026.css',
    'student/student-app-cinematic-v57.css',
    'shared/theme-smoke-v59.css',
    'shared/theme-smoke-v60.css',
    'shared/holiday-smoke-personalities-v61.css',
    'shared/performance-budget-2026.css',
    'shared/neural-cinema-v61.css',
]

STUDENT_JS = [
    # 00 · Detect constrained clients before starting visual renderers
    'shared/performance-budget-2026.js',
    # 01 · Student App experience
    'student/student_app.js',
    'student/pro-student-experience.js',
    # 02 · Shared visual lifecycle
    'shared/cosmos-world-2026.js',
    'shared/page-entry-motion.js',
    'shared/admin-console-entry-v52.js',
]


def _copy_standalone(files: list[str], source_root: Path, output_root: Path) -> None:
    """Publish individual frontend files without changing their public URLs."""
    for name in files:
        source = source_root / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing standalone frontend asset: {source}")
        target = output_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        print(f"Published {target.relative_to(ROOT)}")


def _write_bundle(files: list[str], output: Path, source_root: Path, area: str) -> None:
    """Concatenate ordered source files and preserve source boundaries."""
    chunks = [
        f"/* GENERATED FILE — {output.name}. Edit frontend/assets/{area}/ and rebuild. */\n"
    ]
    seen: set[str] = set()
    for relative_name in files:
        if relative_name in seen:
            raise ValueError(f"Duplicate asset in bundle manifest: {relative_name}")
        seen.add(relative_name)
        source = source_root / relative_name
        if not source.is_file():
            raise FileNotFoundError(f"Missing frontend asset: {source}")
        source_label = f"frontend/assets/{area}/{relative_name}"
        chunks.extend([
            f"\n/* ===== BEGIN {source_label} ===== */\n",
            source.read_text(encoding="utf-8"),
            f"\n/* ===== END {source_label} ===== */\n",
        ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(chunks), encoding="utf-8", newline="\n")
    print(f"Built {output.relative_to(ROOT)} ({len(files)} source files)")


def _write_legacy_portal_bundle() -> None:
    """Generate the legacy portal.css compatibility bundle from canonical source."""
    chunks = ["/* Generated by scripts/build_assets.py; do not edit by hand. */\n"]
    for name in LEGACY_PORTAL_CSS:
        source = (STYLE_SOURCE / 'portal' / name) if name == 'ui-polish.css' else (STANDALONE_CSS_SOURCE / name)
        if not source.is_file():
            raise FileNotFoundError(f"Missing legacy stylesheet source: {source}")
        chunks.extend([
            f"\n/* ===== BEGIN frontend/assets/standalone/css/{name} ===== */\n",
            source.read_text(encoding="utf-8"),
            f"\n/* ===== END frontend/assets/standalone/css/{name} ===== */\n",
        ])
    (PUBLIC_CSS / 'portal.css').write_text("".join(chunks), encoding="utf-8", newline="\n")
    print(f"Built {(PUBLIC_CSS / 'portal.css').relative_to(ROOT)}")


def build() -> None:
    """Publish standalone files and build portal + Student App bundles."""
    PUBLIC_CSS.mkdir(parents=True, exist_ok=True)
    PUBLIC_JS.mkdir(parents=True, exist_ok=True)

    _copy_standalone(STANDALONE_CSS, STANDALONE_CSS_SOURCE, PUBLIC_CSS)
    shutil.copyfile(STYLE_SOURCE / 'portal' / 'ui-polish.css', PUBLIC_CSS / 'ui-polish.css')
    print(f"Published {(PUBLIC_CSS / 'ui-polish.css').relative_to(ROOT)} from canonical portal source")
    # Remove obsolete duplicated UI-polish releases from the public directory.
    for old_version in range(5, 9):
        (PUBLIC_CSS / f'ui-polish-v{old_version}.css').unlink(missing_ok=True)
    _copy_standalone(STANDALONE_JS, STANDALONE_JS_SOURCE, PUBLIC_JS)
    _write_legacy_portal_bundle()

    _write_bundle(SITE_CSS, PUBLIC_CSS / 'site.bundle.css', STYLE_SOURCE, "styles")
    _write_bundle(SITE_JS, PUBLIC_JS / 'site.bundle.js', SCRIPT_SOURCE, "scripts")
    _write_bundle(STUDENT_CSS, PUBLIC_CSS / 'student-app.bundle.css', STYLE_SOURCE, "styles")
    _write_bundle(STUDENT_JS, PUBLIC_JS / 'student-app.bundle.js', SCRIPT_SOURCE, "scripts")


if __name__ == "__main__":
    build()
