frappe.pages["drive"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Drive"),
		single_column: true,
		hide_sidebar: true,
	});
	page.page_head.hide();
	const main = page.main.get(0);
	main.style.padding = "0";
	main.style.height = "calc(100vh - 48px)";
	main.style.overflow = "hidden";
	main.innerHTML =
		'<iframe src="/drive?embed=1" title="Drive" style="width:100%;height:100%;border:0;display:block;background:#f8fafd"></iframe>';
};
