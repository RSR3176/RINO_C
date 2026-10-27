# junit-demo (Rino sample)

Primary sandbox fixture for Steps 3–7:

| File | Seeded signal |
|------|----------------|
| `shellutil.py` | Bandit `B602` (Critical → fix + PR demo) |
| `messy.py` | Pylint undefined name / style |
| `tests/…::test_missing_optional_dependency` | `ModuleNotFoundError` → Environment (not a code bug) |
| `mathutil.py` + other tests | Passing pytest |

Also seed `payments-core` (core-module failing test) and `auth-service` (hardcoded password).

```bash
pip install -r requirements.txt
pytest --junitxml=rino-junit.xml
```
