"""Tests for my_project module."""

import pytest

from my_project import __version__, add, greet


def test_version() -> None:
    """Version should be a string."""
    assert isinstance(__version__, str)
    assert __version__ == "0.1.0"


def test_greet() -> None:
    """Greet should return proper greeting."""
    assert greet("World") == "Hello, World!"
    assert greet("Alice") == "Hello, Alice!"


def test_greet_empty() -> None:
    """Greet should handle empty string."""
    assert greet("") == "Hello, !"


def test_add() -> None:
    """Add should return sum of two numbers."""
    assert add(1, 2) == 3
    assert add(0, 0) == 0
    assert add(-1, 1) == 0


def test_add_negative() -> None:
    """Add should handle negative numbers."""
    assert add(-5, -3) == -8
    assert add(-10, 5) == -5


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (2, 7),
        (-4, 9),
        (0, -3),
    ],
)
def test_add_commutative(left: int, right: int) -> None:
    """Add should be commutative across representative integer inputs."""
    assert add(left, right) == add(right, left)
