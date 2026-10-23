import math

import frappe
from frappe.model.document import Document

COMPONENTS = ("Epoxy Top coat", "PU Top coat", "Screed", "Primer", "Coving", "Hi-build")


BUDGET_COMPONENTS = COMPONENTS + ("Applicator",)


COMPONENT_ALIASES = {
	"Top coat": "Epoxy Top coat",
}


COMPONENT_GM_FIELD = {
	"Epoxy Top coat": "top_coat_gm",
	"PU Top coat": "pu_top_coat_gm",
	"Screed": "screed_gm",
	"Primer": "primer_gm",
	"Coving": "coving_gm",
	"Hi-build": "hibuild_gm",
}


TOP_COAT_OPTS = ("0", "500 micron", "1mm", "2mm", "3mm", "4mm")


EPOXY_TOP_COAT_OPTS = ("500 micron", "1mm", "2mm", "3mm", "4mm")


PU_TOP_COAT_OPTS = ("1mm", "2mm", "3mm", "4mm")


SCREED_OPTS = ("0", "500 micron", "1mm", "2mm", "3mm", "4mm", "5mm", "6mm", "7mm")


SQFT_PER_SQM = 10.7639


DEFAULT_RATES = {
	"top_coat_rate": 4230,
	"pu_top_coat_rate": 4230,
	"screed_rate": 3580,
	"primer_rate": 2012,
	"hibuild_rate": 1650,
	"coving_rate": 2800,
	"default_applicator_rate": 10,
	"top_coat_gm": 0,
	"pu_top_coat_gm": 0,
	"screed_gm": 0,
	"primer_gm": 0,
	"hibuild_gm": 0,
	"coving_gm": 0,
}


DEFAULT_COVERAGE = {
	"top_coat_500_coverage": 193,
	"top_coat_1mm_coverage": 139,
	"top_coat_2mm_coverage": 107,
	"top_coat_3mm_coverage": 107,
	"top_coat_4mm_coverage": 107,
	"pu_top_coat_1mm_coverage": 139,
	"pu_top_coat_2mm_coverage": 107,
	"pu_top_coat_3mm_coverage": 107,
	"pu_top_coat_4mm_coverage": 107,
	"screed_500_coverage": 150,
	"screed_1mm_coverage": 129,
	"screed_2mm_coverage": 96,
	"screed_3mm_coverage": 96,
	"screed_4mm_coverage": 96,
	"screed_5mm_coverage": 96,
	"screed_6mm_coverage": 96,
	"screed_7mm_coverage": 96,
	"primer_coverage": 750,
	"coving_coverage": 150,
}


GM_FIELDNAMES = (
	"top_coat_gm",
	"pu_top_coat_gm",
	"screed_gm",
	"primer_gm",
	"hibuild_gm",
	"coving_gm",
)
