frappe.ui.form.on("Customer Product", {
	refresh(frm) {
		_set_address_query(frm);
		_set_section_visibility(frm);
	},

	customer(frm) {
		_set_address_query(frm);
		// Clear address fields when customer changes
		frm.set_value("delivery_address", "");
		frm.set_value("delivery_city", "");
		frm.set_value("delivery_country", "");
		frm.set_value("is_export", 0);

		// Auto-set the customer's default shipping/billing address
		if (frm.doc.customer) {
			_set_default_address(frm);
		}
	},

	packaging_material(frm) {
		if (!frm.doc.packaging_material) return;
		frappe.db.get_value("Packaging Material", frm.doc.packaging_material, "fill_quantity_kg").then(r => {
			if (r && r.message && r.message.fill_quantity_kg) {
				frm.set_value("fill_quantity_kg", r.message.fill_quantity_kg);
			}
		});
	},

	delivery_address(frm) {
		if (!frm.doc.delivery_address) {
			frm.set_value("delivery_city", "");
			frm.set_value("delivery_country", "");
			frm.set_value("is_export", 0);
			return;
		}
		frappe.db.get_value("Address", frm.doc.delivery_address, ["city", "country"]).then(r => {
			if (!r || !r.message) return;
			const { city, country } = r.message;
			frm.set_value("delivery_city", city || "");
			frm.set_value("delivery_country", country || "");
			_update_export_flag(frm, country);
		});
	},
});

function _set_address_query(frm) {
	frm.set_query("delivery_address", () => ({
		query: "frappe.contacts.doctype.address.address.address_query",
		filters: {
			link_doctype: "Customer",
			link_name: frm.doc.customer || "",
		},
	}));
}

function _set_default_address(frm) {
	// Find the customer's primary shipping address
	frappe.call({
		method: "frappe.contacts.doctype.address.address.get_default_address",
		args: { doctype: "Customer", name: frm.doc.customer },
	}).then(r => {
		const addr = r && r.message;
		if (addr) {
			frm.set_value("delivery_address", addr);
		}
	});
}

function _set_section_visibility(frm) {
	const roles = frappe.user_roles;
	const isSales = roles.includes("Costing Sales") || roles.includes("System Manager");
	const isRD = roles.includes("R&D Manager") || roles.includes("System Manager");

	// Formulations: R&D can edit, everyone else sees read-only (never hidden)
	frm.set_df_property("formulations", "read_only", isRD ? 0 : 1);

	// Sales-owned fields: read-only for R&D-only users
	if (!isSales && isRD) {
		[
			"customer", "customer_product_code", "product_description",
			"packaging_material", "fill_quantity_kg", "packaging_description",
			"delivery_address",
		].forEach(f => frm.set_df_property(f, "read_only", 1));
	}
}

function _update_export_flag(frm, country) {
	if (!country) {
		frm.set_value("is_export", 0);
		return;
	}
	frappe.db.get_value("Country", country, "country_name").then(r => {
		if (r && r.message) {
			frm.set_value("is_export", r.message.country_name !== "India" ? 1 : 0);
		}
	});
}
