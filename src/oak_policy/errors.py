"""Domain errors returned by the policy gateway."""


class OakPolicyError(RuntimeError):
    """Base class for expected policy or environment failures."""


class ConfigurationError(OakPolicyError):
    """The policy configuration is missing or invalid."""


class CommandError(OakPolicyError):
    """An external command failed."""


class PolicyDenied(OakPolicyError):
    """A requested operation violated policy."""

    def __init__(self, message: str, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or [message]
