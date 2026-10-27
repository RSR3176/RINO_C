"""Fix generation (Step 6) — verified patches only; no push/PR yet."""

from app.fix.safety import SafetyResult, validate_patch_files

__all__ = ["SafetyResult", "validate_patch_files"]
