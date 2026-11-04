function open_compliance_calendar() {
	frappe.route_flags.replace_route = true;
	frappe.set_route("List", "Compliance Activity", "Calendar", "default");
}

frappe.pages["compliance-calendar"].on_page_load = function () {
	open_compliance_calendar();
};

frappe.pages["compliance-calendar"].on_page_show = function () {
	open_compliance_calendar();
};
