"""Intentional bandit finding for Step 4 demos."""

import subprocess


def run_user_command(cmd: str) -> str:
    # Bandit B602: subprocess call with shell=True
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
    return result.stdout
