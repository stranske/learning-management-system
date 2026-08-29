"""Guard against unreachable design-system Python modules."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN_SYSTEM_DIR = ROOT / "design-system"
SRC_DIR = ROOT / "src"

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
        for match in IMPORT_PATTERN.finditer(
            "import ds_colors\nfrom ds_spacing import GAP\n"
        )
    }
    assert targets == {"ds_colors", "ds_spacing"}


def test_every_design_system_module_has_an_importer() -> None:
    """Every design-system/*.py module must be imported somewhere under src/."""
    modules = sorted(path.stem for path in DESIGN_SYSTEM_DIR.glob("*.py"))
    if not modules:
        return

    imported = _collect_src_import_targets()
    unimported = [name for name in modules if name not in imported]
    assert not unimported, (
        "design-system modules without an importer under src/: "
        + ", ".join(unimported)
    )
