import frappe

class RateConflictError(frappe.ValidationError):
    """Raised when a rate validity overlap is detected."""
    def __init__(self, message, conflicting_name=None, conflicting_valid_from=None, conflicting_valid_to=None):
        super().__init__(message)
        self.conflicting_name = conflicting_name
        self.conflicting_valid_from = conflicting_valid_from
        self.conflicting_valid_to = conflicting_valid_to
