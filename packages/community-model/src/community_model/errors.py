"""Stable, structured failures for inert model validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

PathPart: TypeAlias = str | int


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One deterministic validation failure suitable for tests and audit mapping."""

    reason_code: str
    message: str
    path: tuple[PathPart, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or not self.reason_code:
            raise TypeError("validation reason code must be a nonempty string")
        if not isinstance(self.message, str) or not self.message:
            raise TypeError("validation message must be a nonempty string")
        if not isinstance(self.path, list | tuple) or any(
            isinstance(part, bool)
            or not isinstance(part, str | int)
            or isinstance(part, str)
            and not part
            for part in self.path
        ):
            raise TypeError("validation path must contain string/integer parts")
        object.__setattr__(self, "path", tuple(self.path))

    @property
    def dotted_path(self) -> str:
        if not self.path:
            return "$"
        rendered = "$"
        for part in self.path:
            rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
        return rendered


class ValidationError(ValueError):
    """A typed validation failure with a stable reason code and value path."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        path: tuple[PathPart, ...] = (),
    ) -> None:
        self.issue = ValidationIssue(reason_code, message, path)
        super().__init__(
            f"{self.issue.reason_code} at {self.issue.dotted_path}: {self.issue.message}"
        )

    @property
    def reason_code(self) -> str:
        return self.issue.reason_code

    @property
    def path(self) -> tuple[PathPart, ...]:
        return self.issue.path


class PortError(RuntimeError):
    """Base class for expected adapter failures at a service-owned port."""


class PortUnavailableError(PortError):
    """The adapter cannot currently complete a read or write."""


class ImmutableConflictError(PortError):
    """A deterministic authority key is occupied by incompatible content."""


class AuthorizationError(PortError):
    """The local caller is not authorized for the requested operation."""


class CredentialUnavailableError(PortError):
    """The configured credential reference cannot be resolved."""


class UnsupportedReadmissionError(PortError):
    """A valid removal already terminalizes this exact subject lifecycle."""


class WriteFailedError(PortError):
    """An authority write failed or remained ambiguous after the attempt."""


class CursorError(PortError):
    """A caller supplied an invalid or unsupported opaque cursor."""
