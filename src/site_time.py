"""Site-local, DST-aware schedule helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def require_site_timezone(config: dict) -> ZoneInfo:
    """Validate and return the deployment's required IANA site timezone."""
    name = str((config.get("site") or {}).get("timezone") or "").strip()
    if not name:
        raise ValueError("site.timezone is required (use an IANA name such as America/Chicago)")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"site.timezone is not a recognized IANA timezone: {name}") from exc


def site_time(timestamp: float, context):
    """Return a struct_time in the validated timezone carried by the pipeline."""
    timezone = getattr(context, "timezone", None)
    if timezone is None:
        raise RuntimeError("pipeline context is missing a validated site timezone")
    if isinstance(timezone, str):
        try:
            timezone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError(f"unrecognized site timezone: {timezone}") from exc
    return datetime.fromtimestamp(timestamp, timezone).timetuple()
