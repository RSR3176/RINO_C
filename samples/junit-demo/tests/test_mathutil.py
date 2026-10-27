import pytest

from mathutil import add, divide


def test_add():
    assert add(2, 3) == 5


def test_divide():
    assert divide(10, 2) == 5


def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_missing_optional_dependency():
    """Fails with ModuleNotFoundError — triaged as environment (not a code bug)."""
    import definitely_not_installed_rino_pkg  # noqa: F401
