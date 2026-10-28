class ProjError(Exception):
    """Expected user-facing error."""


class MetadataError(ProjError):
    """Invalid project metadata."""


class AccessDenied(MetadataError):
    """The person may not read something an environment points to (its project root).

    Not a broken environment: it is counted with the ones the person cannot read.
    """


class ConfigError(ProjError):
    """Invalid proj configuration."""
