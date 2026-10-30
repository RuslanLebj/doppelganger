class BackupNotFound(Exception):
    """Requested backup configuration or run does not exist."""


class BackupConflict(Exception):
    """The operation conflicts with the current backup state."""
