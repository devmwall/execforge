class OrchestratorError(Exception):
    """Base exception for expected orchestration failures."""


class ConfigError(OrchestratorError):
    """Raised when config/state is missing or invalid."""


class RepoError(OrchestratorError):
    """Raised for git or repository state issues."""


class BackendError(OrchestratorError):
    """Raised for backend invocation failures."""


class ValidationError(OrchestratorError):
    """Raised when one or more validations fail."""
