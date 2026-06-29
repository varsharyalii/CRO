"""Phase 0.2 — every surface_map path must exist under JHAAZI_FRONTEND_PATH.

The grounding harness rejects recommendations citing nonexistent files, so the
hand-authored map must stay in sync with the real frontend. Skipped if the
frontend checkout isn't present (CI without the sibling repo)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cro_agent.config import settings
from cro_agent.surface_map import DEFAULT_SURFACE, SURFACE_MAP


def _frontend_root() -> Path:
    return Path(settings.jhaazi_frontend_path)


pytestmark = pytest.mark.skipif(
    not _frontend_root().exists(),
    reason=f"jhaazi-frontend not found at {settings.jhaazi_frontend_path}",
)


def test_every_surface_map_path_exists():
    root = _frontend_root()
    missing: list[str] = []
    for label, surface in SURFACE_MAP.items():
        for rel in surface.files:
            if not (root / rel).exists():
                missing.append(f"{label}: {rel}")
    assert not missing, "surface_map paths do not exist:\n" + "\n".join(missing)


def test_default_surface_path_exists():
    assert (_frontend_root() / DEFAULT_SURFACE.files[0]).exists()
