#!/usr/bin/env python3
"""
Xfloor ERPNext seed script.
Idempotent: safe to run multiple times. Creates if missing, updates if exists.

Usage:
    pip install requests
    python seed.py --host https://your-erpnext.com --key YOUR_KEY --secret YOUR_SECRET
    python seed.py --host https://your-erpnext.com --key YOUR_KEY --secret YOUR_SECRET --dry-run

Env var alternative (avoids passing secrets on CLI):
    export FRAPPE_API_BASE_URL=https://your-erpnext.com
    export FRAPPE_API_KEY=your_key
    export FRAPPE_API_SECRET=your_secret
    python seed.py
"""

import argparse
import json
import os
import sys

import requests

# ---------------------------------------------------------------------------
# CLI / config
# ---------------------------------------------------------------------------


def parse_args():
	p = argparse.ArgumentParser(description="Seed Xfloor ERPNext custom app doctypes.")
	p.add_argument("--host", default=os.getenv("FRAPPE_API_BASE_URL"), help="ERPNext base URL")
	p.add_argument("--key", default=os.getenv("FRAPPE_API_KEY"), help="API key")
	p.add_argument("--secret", default=os.getenv("FRAPPE_API_SECRET"), help="API secret")
	p.add_argument("--dry-run", action="store_true", help="Print actions without writing")
	args = p.parse_args()
	missing = [n for n, v in [("--host", args.host), ("--key", args.key), ("--secret", args.secret)] if not v]
	if missing:
		p.error(f"Missing: {', '.join(missing)}")
	return args


# ---------------------------------------------------------------------------
# ERPNext client
# ---------------------------------------------------------------------------


class ERPNextClient:
	def __init__(self, host: str, key: str, secret: str, dry_run: bool = False):
		self.host = host.rstrip("/")
		self.dry_run = dry_run
		self.session = requests.Session()
		self.session.headers.update(
			{
				"Authorization": f"token {key}:{secret}",
				"Content-Type": "application/json",
				"Accept": "application/json",
			}
		)

	def _url(self, path: str) -> str:
		return f"{self.host}{path}"

	def get(self, doctype: str, name: str) -> dict | None:
		"""Return doc dict or None if not found."""
		try:
			r = self.session.get(self._url(f"/api/resource/{doctype}/{name}"))
			if r.status_code == 404:
				return None
			r.raise_for_status()
			return r.json().get("data")
		except requests.HTTPError as e:
			print(f"  ERROR get {doctype}/{name}: {e}")
			return None

	def upsert(self, doctype: str, name: str, data: dict) -> bool:
		"""
		Create if not exists, update if exists.
		For singletons pass name == doctype.
		"""
		existing = self.get(doctype, name)
		if self.dry_run:
			action = "UPDATE" if existing else "CREATE"
			print(f"  [DRY RUN] {action} {doctype}/{name}")
			return True

		if existing:
			r = self.session.put(
				self._url(f"/api/resource/{doctype}/{name}"),
				data=json.dumps(data),
			)
		else:
			payload = {"doctype": doctype, **data}
			if name != doctype:
				payload["name"] = name
			r = self.session.post(
				self._url(f"/api/resource/{doctype}"),
				data=json.dumps(payload),
			)

		try:
			r.raise_for_status()
			print(f"  {'updated' if existing else 'created'} {doctype}/{name}")
			return True
		except requests.HTTPError:
			print(f"  FAIL {doctype}/{name}: {r.status_code} {r.text[:300]}")
			return False

	def upsert_singleton(self, doctype: str, data: dict) -> bool:
		return self.upsert(doctype, doctype, data)

	def find_by_field(self, doctype: str, field: str, value: str) -> str | None:
		"""Return name of first doc where field == value, or None."""
		r = self.session.get(
			self._url(f"/api/resource/{doctype}"),
			params={
				"filters": json.dumps([[field, "=", value]]),
				"fields": json.dumps(["name", field]),
				"limit_page_length": 1,
			},
		)
		r.raise_for_status()
		rows = r.json().get("data", [])
		return rows[0]["name"] if rows else None

	def upsert_auto(self, doctype: str, unique_field: str, data: dict) -> bool:
		"""
		Upsert an auto-named doc (Testimonial, Gallery Item).
		Uses unique_field for idempotent lookup.
		"""
		existing_name = self.find_by_field(doctype, unique_field, data[unique_field])
		if self.dry_run:
			action = "UPDATE" if existing_name else "CREATE"
			print(f"  [DRY RUN] {action} {doctype} [{unique_field}={data[unique_field]!r:.60}]")
			return True

		if existing_name:
			r = self.session.put(
				self._url(f"/api/resource/{doctype}/{existing_name}"),
				data=json.dumps(data),
			)
		else:
			r = self.session.post(
				self._url(f"/api/resource/{doctype}"),
				data=json.dumps({"doctype": doctype, **data}),
			)

		try:
			r.raise_for_status()
			action = "updated" if existing_name else "created"
			print(f"  {action} {doctype} [{data[unique_field]!r:.60}]")
			return True
		except requests.HTTPError:
			print(f"  FAIL {doctype} [{data[unique_field]!r:.60}]: {r.status_code} {r.text[:300]}")
			return False


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

from mpd_customizations.xfloor_cms.seed_data import (  # noqa: E402
	ABOUT_PAGE,
	APPLICATOR_PAGE,
	CONTACT_PAGE,
	FAQ_PAGE,
	GALLERY_ITEMS,
	HOME_PAGE,
	INDUSTRIES,
	PRODUCTS,
	SITE_SETTINGS,
	TESTIMONIALS,
)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
	args = parse_args()
	client = ERPNextClient(args.host, args.key, args.secret, dry_run=args.dry_run)
	errors = 0

	print("\n=== Singleton Pages ===")
	for doctype, data in [
		("XF Site Settings", SITE_SETTINGS),
		("XF Home Page", HOME_PAGE),
		("XF About Page", ABOUT_PAGE),
		("XF Applicator Page", APPLICATOR_PAGE),
		("XF Contact Page", CONTACT_PAGE),
		("XF FAQ Page", FAQ_PAGE),
	]:
		if not client.upsert_singleton(doctype, data):
			errors += 1

	print("\n=== Product Systems ===")
	for p in PRODUCTS:
		# The REST upsert addresses the record by name; the shared seed data
		# does not carry one, so derive it from the system code.
		payload = {"name": p["system_code"], **p}
		if not client.upsert("XF Product System", p["system_code"], payload):
			errors += 1

	print("\n=== Industry Profiles ===")
	for ind in INDUSTRIES:
		if not client.upsert("XF Industry Profile", ind["name"], ind):
			errors += 1

	print("\n=== Testimonials ===")
	for t in TESTIMONIALS:
		if not client.upsert_auto("XF Testimonial", "author", t):
			errors += 1

	print("\n=== Gallery Items ===")
	for g in GALLERY_ITEMS:
		if not client.upsert_auto("XF Gallery Item", "caption", g):
			errors += 1

	label = "DRY RUN — " if args.dry_run else ""
	print(f"\n{label}Done. {errors} error(s).")
	sys.exit(1 if errors else 0)


if __name__ == "__main__":
	main()
