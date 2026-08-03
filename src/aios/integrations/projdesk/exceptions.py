"""ProjDesk integration — domain exceptions."""


class ProjDeskError(Exception):
    def __init__(self, details: str = "") -> None:
        self.details = details
        super().__init__(details or "ProjDesk communication failed")


class ProjectNotFound(ProjDeskError):
    def __init__(self, project: str) -> None:
        self.project = project
        super().__init__(f"Project not found: {project}")


class ProjectAmbiguous(ProjDeskError):
    def __init__(self, project: str) -> None:
        self.project = project
        super().__init__(f"Multiple projects match '{project}'. Be more specific.")
