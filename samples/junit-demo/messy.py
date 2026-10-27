"""Intentional pylint findings for Step 4 demos."""

import os  # unused — pylint W0611 / similar


def broken_add(a, b):  # missing type hints / style
    return a + c  # undefined name — pylint E0602
