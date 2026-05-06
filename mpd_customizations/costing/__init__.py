class RateConflictError(Exception):
	def __init__(self, conflicting_name, conflicting_valid_from, conflicting_valid_to):
		self.conflicting_name = conflicting_name
		self.conflicting_valid_from = conflicting_valid_from
		self.conflicting_valid_to = conflicting_valid_to
		super().__init__(f"Rate conflict with {conflicting_name}")
