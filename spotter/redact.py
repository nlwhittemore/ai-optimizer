"""Secrets never enter the record. Applied to every prompt and reply at ingest."""
import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),                 # OpenAI / Anthropic style keys
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),             # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),          # Slack
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),                # Google API key
    re.compile(r"sl\.[A-Za-z0-9_\-]{40,}"),                # Dropbox short-lived token
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),   # JWT
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{24,}"),
]


def redact(text: str) -> tuple[str, int]:
    n = 0
    for rx in _PATTERNS:
        text, k = rx.subn("[secret removed]", text or "")
        n += k
    return text, n
