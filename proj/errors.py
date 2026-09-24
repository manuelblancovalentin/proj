class ProjError(Exception):
    """Expected user-facing error."""


class MetadataError(ProjError):
    """Invalid project metadata."""


class ConfigError(ProjError):
    """Invalid proj configuration."""
