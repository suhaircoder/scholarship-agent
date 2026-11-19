"""Errors raised by configuration, fetching, and delivery."""


class ConfigError(Exception):
    """The YAML configuration is missing or invalid."""


class SourceFetchError(Exception):
    """A single source failed. The run continues with the other sources."""

    def __init__(self, source_id: str, message: str) -> None:
        self.source_id = source_id
        super().__init__(f"{source_id}: {message}")


class EnrichmentError(Exception):
    """The optional model call failed. Heuristic classification still stands."""


class DeliveryError(Exception):
    """One delivery channel failed. Other channels are still attempted."""
