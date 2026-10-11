"""Exceptions that map to CLI exit codes."""

from __future__ import annotations

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_LINT = 3
EXIT_SOURCE_MISSING = 4
EXIT_DRIFT = 5


class SagasError(Exception):
    """Base error; `exit_code` is what the CLI returns."""

    exit_code = EXIT_ERROR


class ConfigError(SagasError):
    """A landmark.toml is invalid."""

    exit_code = EXIT_USAGE


class SourceMissing(SagasError):
    """The source model is not downloaded yet (or needs a manual download)."""

    exit_code = EXIT_SOURCE_MISSING
