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
        ds_(?P<ds_module>[A-Za-z0-9_]+)
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
