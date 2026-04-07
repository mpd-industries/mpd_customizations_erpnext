"""Setuptools shim for tooling that expects setup.py. Prefer pyproject.toml + flit."""

from setuptools import find_packages, setup

setup(
	name="mpd_customizations",
	version="0.0.1",
	description="Customizations For MPD Industries",
	python_requires=">=3.10",
	packages=find_packages(),
)
