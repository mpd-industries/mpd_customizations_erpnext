import unittest

from mpd_customizations.drive.services.permissions import resolve_level, roots_for_user, visible_names


def _folder(name, parent=None, owner="owner@example.com", inherit=1, permissions=None):
	return {
		"name": name,
		"parent": parent,
		"owner": owner,
		"inherit_permissions": inherit,
		"permissions": permissions or [],
	}


class TestResolveLevel(unittest.TestCase):
	def test_role_grants_view(self):
		folders = {
			"root": _folder(
				"root",
				permissions=[{"principal_type": "Role", "role": "Accounts", "level": "View"}],
			)
		}
		self.assertEqual(resolve_level("root", folders, "user@example.com", {"Accounts"}), "View")

	def test_user_rule_outranks_role(self):
		folders = {
			"root": _folder(
				"root",
				permissions=[
					{"principal_type": "Role", "role": "Accounts", "level": "View"},
					{"principal_type": "User", "user": "user@example.com", "level": "Edit"},
				],
			)
		}
		self.assertEqual(resolve_level("root", folders, "user@example.com", {"Accounts"}), "Edit")

	def test_owner_is_manage(self):
		folders = {"root": _folder("root", owner="owner@example.com")}
		self.assertEqual(resolve_level("root", folders, "owner@example.com", set()), "Manage")

	def test_admin_is_manage(self):
		folders = {"root": _folder("root")}
		self.assertEqual(
			resolve_level("root", folders, "stranger@example.com", set(), is_admin=True),
			"Manage",
		)

	def test_inheritance_reaches_parent(self):
		folders = {
			"root": _folder(
				"root",
				permissions=[{"principal_type": "Role", "role": "Accounts", "level": "Edit"}],
			),
			"child": _folder("child", parent="root"),
		}
		self.assertEqual(resolve_level("child", folders, "user@example.com", {"Accounts"}), "Edit")

	def test_inheritance_stops_at_folder_that_opts_out(self):
		folders = {
			"grand": _folder(
				"grand",
				permissions=[{"principal_type": "Role", "role": "Accounts", "level": "Manage"}],
			),
			"parent": _folder("parent", parent="grand", inherit=0),
			"child": _folder("child", parent="parent"),
		}
		self.assertIsNone(resolve_level("child", folders, "user@example.com", {"Accounts"}))
		self.assertEqual(resolve_level("grand", folders, "user@example.com", {"Accounts"}), "Manage")

	def test_opt_out_folder_keeps_its_own_rules(self):
		folders = {
			"parent": _folder(
				"parent",
				inherit=0,
				permissions=[{"principal_type": "Role", "role": "HR", "level": "View"}],
			)
		}
		self.assertEqual(resolve_level("parent", folders, "user@example.com", {"HR"}), "View")
		self.assertIsNone(resolve_level("parent", folders, "user@example.com", {"Accounts"}))


class TestListing(unittest.TestCase):
	def test_shared_child_appears_when_parent_is_hidden(self):
		folders = {
			"root": _folder("root", inherit=0),
			"shared": _folder(
				"shared",
				parent="root",
				inherit=0,
				permissions=[{"principal_type": "User", "user": "user@example.com", "level": "View"}],
			),
		}
		visible = visible_names(folders, "user@example.com", set())
		self.assertEqual(visible, ["shared"])
		self.assertEqual(roots_for_user(folders, "user@example.com", set()), ["shared"])

	def test_manage_filter_excludes_view(self):
		folders = {
			"root": _folder(
				"root",
				permissions=[{"principal_type": "Role", "role": "Accounts", "level": "View"}],
			)
		}
		self.assertEqual(visible_names(folders, "user@example.com", {"Accounts"}, min_level="Manage"), [])
		self.assertEqual(visible_names(folders, "user@example.com", {"Accounts"}, min_level="View"), ["root"])
