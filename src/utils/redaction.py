"""Secret redaction for logs and stored errors.

A `requests` network error's message contains the full URL, query string
included, and Adzuna authenticates with `?app_id=...&app_key=...`. So a
network blip used to write the Adzuna key into logs (and into any stored
error text). Two layers keep secrets out:

- `redact(text, secrets)` replaces every non-empty secret value, plus any
  `app_id=` / `app_key=` query value, with `***`. Used on every error
  stored in `ingestion_runs.error`.
- `RedactingFilter`, a `logging.Filter` installed on the handlers the CLIs
  and the daily runner use, applies the same rule to every formatted
  message and traceback.

Secrets are the credential values in Settings: Adzuna app_id and app_key,
USAJobs key and user-agent email (treated as secret too).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from src.utils.config import Settings

MASK = "***"
_QUERY_SECRET = re.compile(r"(\bapp_(?:id|key)=)[^&\s'\"]+", re.IGNORECASE)


def redact(text: str | None, secrets: Iterable[str] = ()) -> str | None:
    if text is None:
        return None
    # longest first, so a secret containing another is masked whole
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return _QUERY_SECRET.sub(rf"\g<1>{MASK}", text)


def secrets_from_settings(settings: Settings) -> list[str]:
    return [
        settings.adzuna_app_id,
        settings.adzuna_app_key,
        settings.usajobs_api_key,
        settings.usajobs_user_agent_email,
    ]


class RedactingFilter(logging.Filter):
    """Rewrites each record's message (and traceback text) with `redact`."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message, self.secrets)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text, self.secrets)
        return True


def install_redaction(
    secrets: Iterable[str], handlers: Iterable[logging.Handler] | None = None
) -> RedactingFilter:
    """Add one RedactingFilter to `handlers` (default: the root logger's)."""
    filt = RedactingFilter(secrets)
    for handler in handlers if handlers is not None else logging.getLogger().handlers:
        handler.addFilter(filt)
    return filt
