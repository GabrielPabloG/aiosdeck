"""ProjDesk integration — domain client for workspace resolution."""

from aios.integrations.projdesk.client import ProjDeskClient
from aios.integrations.projdesk.exceptions import (
    ProjDeskError,
    ProjectAmbiguous,
    ProjectNotFound,
)

__all__ = [
    "ProjDeskClient",
    "ProjDeskError",
    "ProjectNotFound",
    "ProjectAmbiguous",
]
