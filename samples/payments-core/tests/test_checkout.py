import sys
from pathlib import Path

# Allow `src/` layout without install
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from payments.checkout import apply_discount


def test_apply_discount_ten_percent():
    # $10.00 with 10% off → $9.00
    assert apply_discount(1000, 10) == 900


def test_apply_discount_zero():
    assert apply_discount(500, 0) == 500
