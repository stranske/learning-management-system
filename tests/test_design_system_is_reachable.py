"""Guard against unreachable design-system Python modules."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_SYSTEM_DIR = ROOT / "design-system"
SRC_DIR = ROOT / "src"

# The shared design-system directory also carries adapters for other consumer runtimes. LMS is a
# FastAPI/web application and consumes the CSS design system; importing the Streamlit adapter into
# its application graph would add a runtime dependency that this service neither needs nor uses.
OTHER_RUNTIME_ADAPTERS = {"ds_streamlit"}

IMPORT_PATTERN = re.compile(
    r"""(?x)
    ^\s*(?:from|import)\s+
    (?:
        design_system\.(?P<module>[A-Za-z0-9_]+)
        |
        design-system\.(?P<dash_module>[A-Za-z0-9_]+)
        |
        (?P<ds_module>ds_[A-Za-z0-9_]+)
    )
    """,
    re.MULTILINE,
)


def _collect_src_import_targets() -> set[str]:
    targets: set[str] = set()
    for path in SRC_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in IMPORT_PATTERN.finditer(text):
            module = match.group("module") or match.group("dash_module") or match.group("ds_module")
            if module:
                targets.add(module)
    return targets


def test_import_pattern_keeps_ds_prefix_for_direct_imports() -> None:
    """Direct ds_ imports normalize to their design-system module filenames."""
    targets = {
        match.group("module") or match.group("dash_module") or match.group("ds_module")
        for match in IMPORT_PATTERN.finditer("import ds_colors\nfrom ds_spacing import GAP\n")
    }
    assert targets == {"ds_colors", "ds_spacing"}


def test_every_applicable_design_system_module_has_an_importer() -> None:
    """Every design-system Python module applicable to LMS must be reachable under src/."""
    modules = sorted(
        path.stem
        for path in DESIGN_SYSTEM_DIR.glob("*.py")
        if path.stem not in OTHER_RUNTIME_ADAPTERS
    )
    if not modules:
        return

    imported = _collect_src_import_targets()
    unimported = [name for name in modules if name not in imported]
    assert not unimported, "design-system modules without an importer under src/: " + ", ".join(
        unimported
    )


def test_other_runtime_adapters_stay_out_of_the_lms_import_graph() -> None:
    """Runtime-specific adapters must not create unused dependencies in the web service."""
    assert _collect_src_import_targets().isdisjoint(OTHER_RUNTIME_ADAPTERS)
