function open_needs_review() {
	frappe.route_options = { ai_status: "Needs Review" };
	frappe.route_flags.replace_route = true;
	frappe.set_route("List", "Drive File");
}

frappe.pages["drive-needs-review"].on_page_load = function () {
	open_needs_review();
};

frappe.pages["drive-needs-review"].on_page_show = function () {
	open_needs_review();
};
