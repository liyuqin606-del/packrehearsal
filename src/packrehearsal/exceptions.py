"""Domain-specific exceptions surfaced by the CLI."""


class PackRehearsalError(Exception):
    """Base exception for expected, user-actionable failures."""


class ConfigurationError(PackRehearsalError):
    """Raised when configuration is malformed or unsafe."""


class DiscoveryError(PackRehearsalError):
    """Raised when package discovery cannot proceed safely."""


class ArchiveSafetyError(PackRehearsalError):
    """Raised when an artifact violates an archive safety invariant."""


class RehearsalError(PackRehearsalError):
    """Raised when an explicitly trusted package rehearsal fails."""


class ReceiptVerificationError(PackRehearsalError):
    """Raised when an evidence receipt cannot be verified."""
