"""Built-in LLM backends. Import to auto-register.

Backends with missing dependencies are silently skipped — they'll
raise a clear error only if you try to use them via AICOMPANY_LLM_BACKEND.
"""
try:
    from . import anthropic_backend  # noqa: F401
except ImportError:
    pass

try:
    from . import openai_backend  # noqa: F401
except Exception:
    pass

from . import fake_backend  # noqa: F401  — always available, no dependencies
