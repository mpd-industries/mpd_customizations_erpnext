import frappe

ITEM_CATEGORY_CODE_SEED_ROWS = [
    # Oils & Fatty Derivatives
    {"prefix": "VGO", "full_name": "Vegetable & Drying Oil", "domain": "Chemicals", "is_active": 1},
    {"prefix": "FAC", "full_name": "Fatty Acid", "domain": "Chemicals", "is_active": 1},
    {"prefix": "DMA", "full_name": "Dimer Acid & Oligomeric Acid", "domain": "Chemicals", "is_active": 1},
    # Chemical Raw Materials
    {"prefix": "POL", "full_name": "Polyol", "domain": "Chemicals", "is_active": 1},
    {"prefix": "AHD", "full_name": "Anhydride", "domain": "Chemicals", "is_active": 1},
    {"prefix": "ACA", "full_name": "Acid — Aromatic, Organic, Inorganic", "domain": "Chemicals", "is_active": 1},
    {"prefix": "PHN", "full_name": "Phenol & Phenol Derivatives", "domain": "Chemicals", "is_active": 1},
    {"prefix": "MNM", "full_name": "Monomer / Intermediate", "domain": "Chemicals", "is_active": 1},
    {"prefix": "AMN", "full_name": "Amine & Polyamine", "domain": "Chemicals", "is_active": 1},
    {"prefix": "ISO", "full_name": "Isocyanate", "domain": "Chemicals", "is_active": 1},
    {"prefix": "INO", "full_name": "Inorganic Chemical & Aldehyde Source", "domain": "Chemicals", "is_active": 1},
    # Solvents, Additives
    {"prefix": "SOL", "full_name": "Solvent", "domain": "Chemicals", "is_active": 1},
    {"prefix": "CAT", "full_name": "Catalyst, Metal Drier, Metal Salt", "domain": "Chemicals", "is_active": 1},
    {"prefix": "ADD", "full_name": "Additive, Stabiliser, Antioxidant", "domain": "Chemicals", "is_active": 1},
    {"prefix": "PYR", "full_name": "Photoinitiator, Peroxide", "domain": "Chemicals", "is_active": 1},
    {"prefix": "SRF", "full_name": "Surfactant & Emulsifier", "domain": "Chemicals", "is_active": 1},
    {"prefix": "FIL", "full_name": "Filter Medium & Bleaching Earth", "domain": "Chemicals", "is_active": 1},
    {"prefix": "PLT", "full_name": "Plasticiser", "domain": "Chemicals", "is_active": 1},
    {"prefix": "PIG", "full_name": "Pigment & Colorant", "domain": "Chemicals", "is_active": 1},
    {"prefix": "PLM", "full_name": "Polymer", "domain": "Chemicals", "is_active": 1},
    # Resins
    {"prefix": "ALK", "full_name": "Alkyd Resin", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "PES", "full_name": "Polyester Resin", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "PAM", "full_name": "Polyamide Resin", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "EPR", "full_name": "Epoxy Resin", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "EPH", "full_name": "Epoxy Hardener", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "AMR", "full_name": "Amino Resin", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "PHR", "full_name": "Phenolic Resin", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "EST", "full_name": "Ester Gum", "domain": "Resins", "is_active": 1, "requires_solids_suffix": 1},
    {"prefix": "FNP", "full_name": "Finished Pack / Tube Product", "domain": "Resins", "is_active": 1},
    # Packaging
    {
        "prefix": "PKG",
        "full_name": "Packaging Material",
        "domain": "Packaging",
        "is_active": 1,
        "has_sub_category": 1,
        "sub_category_options": "DRM,CAN,CRB,LBL,BOX,SEL",
    },
    # Hardware
    {"prefix": "HRD", "full_name": "Hardware & Fastener", "domain": "Hardware", "is_active": 1},
    {"prefix": "MRO", "full_name": "Maintenance, Repair & Operations", "domain": "Hardware", "is_active": 1},
    {"prefix": "FAB", "full_name": "Fabrication Item", "domain": "Hardware", "is_active": 1},
    # Fixed Assets
    {
        "prefix": "AST",
        "full_name": "Fixed Asset",
        "domain": "Fixed Assets",
        "is_active": 1,
        "has_sub_category": 1,
        "sub_category_options": "PME,LAB,ELE,FUR,VEH,CIV",
    },
    # Services
    {"prefix": "SRV", "full_name": "Service", "domain": "Services", "is_active": 1},
    {"prefix": "UTL", "full_name": "Utility", "domain": "Services", "is_active": 1},
    # Other
    {
        "prefix": "OTH",
        "full_name": "Other / Unclassified",
        "domain": "Other",
        "is_active": 1,
        "llm_guidance_notes": (
            "Use when nothing else fits. Do not force a poor fit. "
            "MA will assign correct prefix before approval."
        ),
    },
]


def seed_item_category_codes():
    for cat in ITEM_CATEGORY_CODE_SEED_ROWS:
        if frappe.db.exists("Item Category Code", cat["prefix"]):
            continue
        doc = frappe.get_doc({"doctype": "Item Category Code", **cat})
        doc.insert(ignore_permissions=True)

    frappe.db.commit()
    print("Seeded Item Category Codes")
