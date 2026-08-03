"""Integrations — external system clients.

Each integration lives in its own package (projdesk/, github/, docker/, ...)
and exposes a client class plus domain exceptions. Import from the specific
package:

    from aios.integrations.projdesk import ProjDeskClient, ProjectNotFound

Integration Rule:
    Never expose subprocess or protocol details. Return domain objects
    or raise domain exceptions. External protocols are translated at
    the integration boundary.
"""
