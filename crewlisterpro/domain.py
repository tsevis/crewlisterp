"""Small, explicit record schema shared by the Python UI and service layer."""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import UTC, date, datetime
from typing import Any, Literal, TypeVar
from uuid import uuid4


def new_id() -> str:
    return uuid4().hex


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


VerificationState = Literal["pending", "verified", "rejected"]
RiskLevel = Literal["low", "review", "high"]
CrewRole = Literal["skipper", "passenger"]


@dataclass(slots=True)
class Boat:
    id: str = field(default_factory=new_id)
    name: str = ""
    flag: str = ""
    registration_port: str = ""
    registration_number: str = ""

    def payload(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class Trip:
    id: str = field(default_factory=new_id)
    boat_id: str = ""
    departure_date: str = ""
    return_date: str = ""
    status: str = "draft"
    created_at: str = field(default_factory=utc_now)

    def payload(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class Person:
    id: str = field(default_factory=new_id)
    full_name: str = ""
    nationality: str = ""
    birth_date: str = ""
    sex: str = ""
    verification_state: VerificationState = "pending"

    def payload(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class Document:
    id: str = field(default_factory=new_id)
    trip_id: str = ""
    person_id: str = ""
    file_name: str = ""
    content_path: str = ""
    sha256: str = ""
    document_number: str = ""
    document_type: str = "unknown"
    risk_level: RiskLevel = "review"
    risk_reasons: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    verified_fields: list[str] = field(default_factory=list)
    source: str = "ocr"
    created_at: str = field(default_factory=utc_now)

    def payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class Assignment:
    id: str = field(default_factory=new_id)
    trip_id: str = ""
    person_id: str = ""
    role: CrewRole = "passenger"

    def payload(self) -> dict[str, str]:
        return asdict(self)


def iso_date(value: date) -> str:
    return value.isoformat()


# --- Reading records back ----------------------------------------------------

#: Fields that join a record to the rest of the store.  A record missing one of
#: these is dropped rather than repaired: every identity field carries
#: ``default_factory=new_id``, so building it anyway would silently mint a
#: *fresh* id, and the record would no longer match the key it is stored under —
#: saving it writes a duplicate instead of an update.
_Record = TypeVar("_Record")

_IDENTITY: dict[type, tuple[str, ...]] = {
    Boat: ("id",),
    Trip: ("id", "boat_id"),
    Person: ("id",),
    Document: ("id", "trip_id", "person_id"),
    Assignment: ("id", "trip_id", "person_id"),
}

#: Fields whose stored value must be one of a fixed set.  ``Literal`` is not
#: enforced at runtime, so a value written by a newer build flows straight
#: through into an exported crew list unless it is normalised here.  Each
#: fallback is the one that makes the operator look: never ``low``, which would
#: read as cleared, and never ``skipper``, which would name the wrong person as
#: master of the vessel.
_VOCABULARY: dict[str, tuple[frozenset[str], str]] = {
    "risk_level": (frozenset({"low", "review", "high"}), "review"),
    "verification_state": (frozenset({"pending", "verified", "rejected"}), "pending"),
    "role": (frozenset({"skipper", "passenger"}), "passenger"),
}


def load_record(cls: type[_Record], payload: dict[str, Any]) -> _Record | None:
    """Build ``cls`` from a stored payload, or ``None`` if it cannot be trusted.

    Unknown keys are dropped rather than raising, so a record written by a newer
    build stays readable by this one.  ``Document(**raw)`` raises ``TypeError``
    on the first unexpected key, and because every read is a list comprehension
    that one record would take its whole collection down with it.

    A field of the wrong shape falls back to its declared default; a field with
    a value outside its vocabulary falls back to the safe end of it.
    """
    known = {field.name: field for field in fields(cls)}  # type: ignore[arg-type]
    for name in _IDENTITY.get(cls, ()):
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            return None

    accepted: dict[str, Any] = {}
    for name, value in payload.items():
        field = known.get(name)
        if field is None:
            continue  # A column this build has never heard of.
        allowed, fallback = _VOCABULARY.get(name, (None, None))
        if allowed is not None:
            accepted[name] = value if value in allowed else fallback
            continue
        # The declared default is what tells us the shape the field expects.
        # Annotations are strings here (`from __future__ import annotations`),
        # so the default — or whatever its factory produces — is the reliable
        # prototype.  Reading only `field.default` misses every
        # `default_factory` field, which includes `id` itself: those were
        # skipped, and the identity this function exists to protect was minted
        # fresh anyway.
        if field.default is not MISSING:
            prototype = field.default
        elif field.default_factory is not MISSING:
            prototype = field.default_factory()
        else:
            prototype = None
        if prototype is not None and not isinstance(value, type(prototype)):
            continue  # Wrong shape entirely: let the dataclass default stand.
        accepted[name] = value
    return cls(**accepted)
