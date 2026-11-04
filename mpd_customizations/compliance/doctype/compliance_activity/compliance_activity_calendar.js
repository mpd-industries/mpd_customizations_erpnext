frappe.views.calendar["Compliance Activity"] = {
	field_map: {
		start: "due_date",
		end: "due_date",
		id: "name",
		title: "title",
	},
	get_events_method: "frappe.desk.calendar.get_events",
};
