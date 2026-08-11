from datetime import datetime
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix.strip('_').lower()}_{uuid4().hex[:16]}"


def timestamp_id(prefix: str) -> str:
    return f"{prefix.strip('_').lower()}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def normalize_account_key(value: str) -> str:
    """THE single shared account-key normalisation (SCHEMA_SPEC §0).

    Every account key comparison/join anywhere in the app must go through this
    one function (SQL equivalent: ``ltrim(trim(x), '0')``): trim surrounding
    whitespace, then strip leading zeros. An input that normalises to empty
    stays "" — never invent a key.
    """
    return str(value).strip().lstrip("0")
