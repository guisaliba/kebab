from datetime import datetime, timezone


ISO_8601_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).strftime(ISO_8601_UTC_FORMAT)


def is_iso8601_utc(value: str) -> bool:
    try:
        parsed = datetime.strptime(value, ISO_8601_UTC_FORMAT)
    except ValueError:
        return False
    return parsed.tzinfo is None
