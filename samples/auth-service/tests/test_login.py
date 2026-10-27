import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auth.login import authenticate


def test_authenticate_ok():
    assert authenticate("admin", "SuperSecretAdmin123!") is True


def test_authenticate_bad():
    assert authenticate("admin", "nope") is False
