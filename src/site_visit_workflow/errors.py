class WorkflowError(Exception):
    """A safe, actionable workflow error."""


class ValidationError(WorkflowError):
    """Input violates a workflow contract."""


class ApprovalRequiredError(WorkflowError):
    """A mutating action has no matching human approval."""


class ExternalServiceError(WorkflowError):
    """An explicitly invoked external service failed."""
