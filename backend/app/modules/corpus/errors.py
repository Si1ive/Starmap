"""Domain errors raised by the corpus application module."""


class CorpusFileNotFoundError(LookupError):
    """Raised when a requested corpus file does not exist."""


class ParseRunNotFoundError(LookupError):
    """Raised when a requested parse run does not exist."""


class ParseConflictError(ValueError):
    """Raised when a parse request conflicts with current file state."""


class DocumentNotFoundError(LookupError):
    """Raised when a requested normalized document does not exist."""


class SourceFileNotFoundError(LookupError):
    """Raised when a document source file cannot be accessed."""


class DocumentPageNotFoundError(LookupError):
    """Raised when a requested source page cannot be rendered."""


class PageRenderError(RuntimeError):
    """Raised when rendering a document page fails."""


class EntityNotFoundError(LookupError):
    """Raised when a requested extracted entity does not exist."""


class EntitySourceUnavailableError(ValueError):
    """Raised when an entity has no traceable source blocks."""


class EntityExtractionConflictError(RuntimeError):
    """Raised when another extraction task is already running."""
