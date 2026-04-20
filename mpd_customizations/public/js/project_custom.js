frappe.ui.form.on("Project", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("New Meeting Note"), async () => {
			// Fetch open task assignees to pre-populate attendees
			const r = await frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Task",
					filters: { project: frm.doc.name, status: ["in", ["Open", "Working", "Pending Review"]] },
					fields: ["_assign"],
					limit: 200,
				},
			});

			// Collect unique assignee user IDs
			const seen = new Set();
			const userIds = [];
			for (const task of (r.message || [])) {
				if (!task._assign) continue;
				let users;
				try { users = JSON.parse(task._assign); } catch { continue; }
				for (const uid of users) {
					if (!seen.has(uid)) {
						seen.add(uid);
						userIds.push(uid);
					}
				}
			}

			// Fetch full_name + email for task assignees
			let userDetails = [];
			if (userIds.length) {
				const ud = await frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "User",
						filters: [["name", "in", userIds]],
						fields: ["name", "full_name", "email"],
						limit: userIds.length,
					},
				});
				userDetails = ud.message || [];
				for (const u of userDetails) seen.add(u.name);
			}

			// Merge attendees from the most recent previous meeting note
			const prevMeetings = await frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Meeting Note",
					filters: { project: frm.doc.name },
					fields: ["name"],
					order_by: "meeting_date desc",
					limit: 1,
				},
			});
			if (prevMeetings.message && prevMeetings.message.length) {
				const prev = await frappe.call({
					method: "frappe.client.get",
					args: { doctype: "Meeting Note", name: prevMeetings.message[0].name },
				});
				for (const att of ((prev.message || {}).attendees || [])) {
					if (att.user && !seen.has(att.user)) {
						seen.add(att.user);
						userDetails.push({ name: att.user, full_name: att.full_name, email: att.email });
					}
				}
			}

			// Build and save doc via API so new tab can fetch it from server
			const now = new Date();
			const timeStr = now.toLocaleString("en-IN", {
				day: "2-digit", month: "short", year: "numeric",
				hour: "2-digit", minute: "2-digit", hour12: true,
			});

			const inserted = await frappe.call({
				method: "frappe.client.insert",
				args: {
					doc: {
						doctype: "Meeting Note",
						title: `${frm.doc.project_name} — ${timeStr}`,
						project: frm.doc.name,
						meeting_date: frappe.datetime.now_datetime(),
						attendees: userDetails.map(u => ({
							doctype: "Meeting Note Attendee",
							user: u.name,
							full_name: u.full_name,
							email: u.email,
						})),
					},
				},
			});

			if (!inserted.message) {
				frappe.msgprint(__("Failed to create Meeting Note"));
				return;
			}

			window.open(frappe.utils.get_form_link("Meeting Note", inserted.message.name), "_blank");
		}, __("Actions"));
	},
});
