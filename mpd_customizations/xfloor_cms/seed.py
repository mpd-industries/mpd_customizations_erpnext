"""
Xfloor CMS — idempotent bench seed script.

Run via bench execute:
    bench --site <site> execute mpd_customizations.xfloor_cms.seed.run

Run from bench console:
    from mpd_customizations.xfloor_cms.seed import run; run()
"""

import frappe


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SITE_SETTINGS = {
	"site_name": "Xfloor.in",
	"default_seo_image": "",
	"contact_phone": "+91 98765 43210",
	"contact_email": "info@xfloor.in",
	"whatsapp_number": "+91 98765 43210",
	"topbar_text": "Supplying High-Performance Coating Systems to Industrial Hubs across India",
	"business_hours": "Mon–Sat, 9 AM – 6 PM IST",
	"footer_brand_tagline": "India's precision industrial floor coating manufacturer. Engineered systems for every substrate, every sector, every scale.",
	"registered_office_address": "MPD Industries Pvt. Ltd. Plot No 59 & 63, Sanwer Rd Industrial Area, Sector A, Indore, Madhya Pradesh 452015",
	"copyright_text": "© 2026 Xfloor — MPD Industries Pvt. Ltd. All rights reserved.",
	"nav_links": [
		{"label": "Home", "url": "/", "sort_order": 1},
		{"label": "Systems & Products", "url": "/products", "sort_order": 2},
		{"label": "About Us", "url": "/about", "sort_order": 3},
		{"label": "Industries", "url": "/industries", "sort_order": 4},
		{"label": "Gallery", "url": "/gallery", "sort_order": 5},
		{"label": "Applicator Program", "url": "/applicator", "sort_order": 6},
		{"label": "FAQ", "url": "/faq", "sort_order": 7},
		{"label": "Contact", "url": "/contact", "sort_order": 8},
	],
	"footer_links": [
		{"column_name": "Products", "label": "Epoxy Systems", "url": "/products", "sort_order": 1},
		{"column_name": "Products", "label": "PU Systems", "url": "/products", "sort_order": 2},
		{"column_name": "Products", "label": "ESD/Anti-Static", "url": "/products", "sort_order": 3},
		{"column_name": "Products", "label": "Hygienic Series", "url": "/products", "sort_order": 4},
		{"column_name": "Products", "label": "Dielectric Coatings", "url": "/products", "sort_order": 5},
		{"column_name": "Company", "label": "About Us", "url": "/about", "sort_order": 1},
		{"column_name": "Company", "label": "Industries", "url": "/industries", "sort_order": 2},
		{"column_name": "Company", "label": "Gallery", "url": "/gallery", "sort_order": 3},
		{"column_name": "Company", "label": "Applicator Program", "url": "/applicator", "sort_order": 4},
		{"column_name": "Company", "label": "Contact Us", "url": "/contact", "sort_order": 5},
		{"column_name": "Resources", "label": "Request TDS", "url": "/contact", "sort_order": 1},
		{"column_name": "Resources", "label": "Request MSDS", "url": "/contact", "sort_order": 2},
		{"column_name": "Resources", "label": "Application Enquiry", "url": "/contact", "sort_order": 3},
		{"column_name": "Resources", "label": "FAQ", "url": "/faq", "sort_order": 4},
	],
	"trust_bar_items": [
		{"text": "ISO 9001:2015 Certified", "sort_order": 1},
		{"text": "FSSAI/HACCP Compliant Systems", "sort_order": 2},
		{"text": "Pan-India Supply & Application", "sort_order": 3},
		{"text": "Free Site Assessment", "sort_order": 4},
	],
	"certifications": [
		{"code": "ISO 9001:2015", "label": "Quality Management System", "accent_color": "#16a34a", "sort_order": 1, "published": 1},
		{"code": "ISO 14001", "label": "Environmental Management", "accent_color": "#1d4ed8", "sort_order": 2, "published": 1},
		{"code": "FSSAI", "label": "Food Safety & Standards", "accent_color": "#16a34a", "sort_order": 3, "published": 1},
		{"code": "HACCP", "label": "Hazard Analysis Certified", "accent_color": "#16a34a", "sort_order": 4, "published": 1},
		{"code": "IEC 61340", "label": "ESD Flooring Standard", "accent_color": "#1d4ed8", "sort_order": 5, "published": 1},
		{"code": "GHS MSDS", "label": "Safety Data Compliance", "accent_color": "#d97706", "sort_order": 6, "published": 1},
	],
	"form_stats": [
		{"number": "50+", "label": "Projects completed", "sort_order": 1},
		{"number": "3+", "label": "States served", "sort_order": 2},
		{"number": "24h", "label": "Quote turnaround", "sort_order": 3},
	],
}

HOME_PAGE = {
	"published": 1,
	"route": "/",
	"meta_title": "Xfloor — Industrial Floor Coating Systems Manufactured in India",
	"meta_description": "High-build epoxy, PU, ESD, and hygienic floor coating systems for manufacturing, food, pharma, and automotive sectors. 500+ projects across 18+ states.",
	"og_type": "website",
	"schema_type": "Organization",
	"hero_eyebrow_text": "Industrial Floor Coating Systems",
	"hero_headline": "Industrial Coatings Engineered for Performance.",
	"hero_subheadline": "High-build epoxy, polyurethane, ESD, and hygienic floor coating systems — manufactured in India, deployed across 500+ industrial sites.",
	"hero_background_image": "",
	"featured_system": "SYS-201",
	"hero_stats": [
		{"number": "50+", "label": "Projects Completed"},
		{"number": "25+", "label": "Years Manufacturing"},
		{"number": "18+", "label": "States Served"},
	],
	"process_steps": [
		{"step_number": "01", "title": "Substrate Preparation", "description": "Diamond grinding, shot blasting, and moisture testing to CSP 3–5 profile."},
		{"step_number": "02", "title": "Xfloor Bond-Prime", "description": "Deep-penetrating primer ensures 0% delamination risk. MPa pull-off > 1.5."},
		{"step_number": "03", "title": "Body Coat (Part A + Part B)", "description": "Resin and hardener mixed at precise stoichiometric ratio. The structural layer."},
		{"step_number": "04", "title": "Xfloor Shield Top Coat", "description": "Scratch, chemical, and UV resistance. Final DFT verified by wet-film gauge."},
	],
	"client_logos_section_title": "Trusted by Industry Leaders",
	"client_logos": [
		{"company_name": "Automotive OEM", "logo": "", "sort_order": 1, "published": 1},
		{"company_name": "Food Conglomerate", "logo": "", "sort_order": 2, "published": 1},
		{"company_name": "Electronics MNC", "logo": "", "sort_order": 3, "published": 1},
		{"company_name": "Pharma Group", "logo": "", "sort_order": 4, "published": 1},
		{"company_name": "Logistics Co.", "logo": "", "sort_order": 5, "published": 1},
		{"company_name": "Steel Plant", "logo": "", "sort_order": 6, "published": 1},
		{"company_name": "Data Centre", "logo": "", "sort_order": 7, "published": 1},
		{"company_name": "FMCG Manufacturer", "logo": "", "sort_order": 8, "published": 1},
	],
	"cta_banner_title": "Ready to Specify Xfloor for Your Project?",
	"cta_banner_subtitle": "Get system recommendations, TDS, and pricing in under 24 hours.",
	"cta_banner_primary_button_text": "Talk to a Specialist",
	"cta_banner_secondary_button_text": "Request TDS Pack",
}

ABOUT_PAGE = {
	"published": 1,
	"route": "/about",
	"meta_title": "About Xfloor — Industrial Coating Manufacturer Since 2012",
	"meta_description": "Xfloor by MPD Yechem. Engineering-first floor coating manufacturer supplying 18+ states. ISO 9001:2015 certified. Our story, values, and timeline.",
	"og_type": "website",
	"schema_type": "Organization",
	"story_title": "From Precision Engineering to National Scale.",
	"story_lead_paragraph": "Xfloor began as an engineering company that understood industrial environments from the inside — the stress on concrete, the chemistry of coatings, and the consequence of failure.",
	"story_body": "Today, we manufacture and supply complete industrial floor coating systems to over 18 states across India — from automotive assembly plants in Pune to pharmaceutical cleanrooms in Ahmedabad. Every product carries our engineering guarantee: zero-compromise adhesion, verifiable performance, documented compliance.",
	"facility_image": "",
	"facility_image_caption": "Manufacturing facility / team at work",
	"timeline_events": [
		{"year": "2012", "title": "Founded in Precision Engineering", "description": "MPD Yechem established as an industrial chemical solutions company serving local manufacturing units."},
		{"year": "2015", "title": "First Epoxy Coating System", "description": "Launched Xfloor Epoxy Series — the first in-house manufactured floor coating system, optimised for concrete substrates."},
		{"year": "2018", "title": "ESD & Hygienic Systems", "description": "Expanded into specialised verticals: ESD anti-static and FSSAI-compliant hygienic series for electronics and food sectors."},
		{"year": "2021", "title": "National Distribution Network", "description": "Established Applicator Partner programme — now active in 18 states with 60+ certified application teams."},
		{"year": "2024", "title": "ISO 9001:2015 Certification", "description": "Full quality management system certification across all product lines."},
	],
	"core_values": [
		{"icon": "engineering", "title": "Engineering-First", "description": "Every formulation is designed for measurable performance — compressive strength, DFT, adhesion pull-off."},
		{"icon": "chemistry", "title": "Cross-Linking Chemistry", "description": "Proprietary cross-linking agents for superior chemical resistance at ambient cure temperatures."},
		{"icon": "reach", "title": "National Reach", "description": "Manufacturing base in India, supply chain across 18+ states."},
	],
}

APPLICATOR_PAGE = {
	"published": 1,
	"route": "/applicator",
	"meta_title": "Xfloor Applicator Partner Programme — Become a Certified Applicator",
	"meta_description": "Join the Xfloor Applicator Programme. Preferential pricing, technical training, project leads, and certified status across India.",
	"og_type": "website",
	"schema_type": "Organization",
	"hero_title": "Build a Flooring Business on India's Most Trusted Coating System.",
	"hero_subtitle": "Become a certified Xfloor Applicator Partner. We provide product supply, technical training, application support, and project leads — you deliver exceptional floors.",
	"program_benefits": [
		{"benefit_text": "Preferential product pricing & credit terms"},
		{"benefit_text": "Certified Applicator status & co-branded collateral"},
		{"benefit_text": "Dedicated technical support on live projects"},
		{"benefit_text": "Priority access to new product systems pre-launch"},
		{"benefit_text": "Direct project lead referrals from our sales team"},
		{"benefit_text": "Free application training at our facility"},
	],
	"program_tiers": [
		{
			"tier_name": "Certified Applicator",
			"requirements": "1+ year in industrial flooring, own grinding equipment",
			"benefits": "Product at trade price, technical support, co-branded certificates",
		},
		{
			"tier_name": "Premier Applicator",
			"requirements": "3+ years, ≥ 5,000 m² completed with Xfloor materials",
			"benefits": "Enhanced margins, project lead referrals, priority support",
		},
		{
			"tier_name": "Master Applicator",
			"requirements": "National capacity, dedicated application crew, 3+ states",
			"benefits": "Maximum margins, joint marketing, exclusive territories, dedicated account manager",
		},
	],
}

CONTACT_PAGE = {
	"published": 1,
	"route": "/contact",
	"meta_title": "Contact Xfloor — Get a Quote, TDS, or Free Site Assessment",
	"meta_description": "Talk to an Xfloor flooring specialist. Request TDS, MSDS, pricing, or a free site assessment. Response within 4 working hours.",
	"og_type": "website",
	"schema_type": "Organization",
	"hero_title": "Talk to a Flooring Specialist.",
	"hero_subtitle": "Separate inquiry channels for direct clients and applicator partners. We respond within 4 working hours.",
	"office_name": "MPD Yechem Pvt Ltd",
	"office_address": "Industrial Area, India",
	"office_address_sub_label": "Manufacturing + Corporate HQ",
	"map_embed_url": "",
	"phone_hours_sub_label": "Mon–Sat, 9 AM – 6 PM IST",
	"email_response_sla": "Responded within 4 working hours",
}

FAQ_PAGE = {
	"published": 1,
	"route": "/faq",
	"meta_title": "Frequently Asked Questions — Xfloor Industrial Floor Coatings",
	"meta_description": "Answers to common questions about Xfloor epoxy, PU, ESD, and hygienic coating systems — coverage, cure time, compliance, and application.",
	"og_type": "website",
	"schema_type": "FAQPage",
	"focus_keyword": "industrial floor coating FAQ India",
	"page_title": "Frequently Asked Questions",
	"page_subtitle": "Everything you need to know about specifying, ordering, and installing Xfloor industrial floor coating systems.",
	"faq_items": [
		{"question": "What is the difference between epoxy and polyurethane floor coatings?", "answer": "Epoxy systems offer superior adhesion and compressive strength, making them ideal for heavy industrial environments. Polyurethane (PU) systems have higher flexibility and UV resistance, making them better suited for outdoor areas, car parks, and zones with thermal cycling. Most high-performance installations use epoxy as the body coat with a PU topcoat.", "sort_order": 1, "published": 1},
		{"question": "How long does an Xfloor coating take to cure before foot traffic?", "answer": "Foot traffic is typically permitted after 24 hours at 25°C. Full chemical resistance is achieved after 7 days. Cure times vary with ambient temperature — lower temperatures extend cure time. Our technical team will advise based on your site conditions.", "sort_order": 2, "published": 1},
		{"question": "Are Xfloor systems FSSAI and HACCP compliant?", "answer": "Yes. The Xfloor Hygienic Series (SYS-401) is specifically formulated for food processing and pharmaceutical environments. Full FSSAI compliance documentation and HACCP certifications are provided before project commencement.", "sort_order": 3, "published": 1},
		{"question": "What surface preparation is required before application?", "answer": "Concrete substrates must be prepared to a CSP 3–5 surface profile using diamond grinding or shot blasting. Moisture content must be below 75% RH. Our application teams carry out a full substrate assessment before any coating is applied.", "sort_order": 4, "published": 1},
		{"question": "Do you supply across all of India?", "answer": "Yes. Xfloor supplies and supports application across 18+ states through our certified Applicator Partner network. Contact us with your project location and we will connect you with the nearest certified team.", "sort_order": 5, "published": 1},
		{"question": "What is the minimum order quantity?", "answer": "Pack sizes are available from 5 Kg + 1 Kg for small areas and patch repairs up to 20 Kg + 4 Kg and bulk supply for large projects. There is no formal minimum order — contact us for project-specific pricing.", "sort_order": 6, "published": 1},
		{"question": "Can Xfloor coatings be applied in occupied facilities?", "answer": "Yes. Xfloor Ultra-Build Epoxy (SYS-201) is a solvent-free, low-odour formulation specifically suitable for occupied or partially occupied facilities. Application can be phased to minimise operational disruption.", "sort_order": 7, "published": 1},
		{"question": "What ESD standard does Xfloor ESD flooring meet?", "answer": "Xfloor ESD Conductive (SYS-302) meets IEC 61340-5-1, with surface resistivity < 10⁶ Ω. Full grounding layout design is included with every ESD project specification — no other vendor provides this as standard.", "sort_order": 8, "published": 1},
		{"question": "How do I become an Xfloor Applicator Partner?", "answer": "Submit an application through our Applicator Programme page. Our Operations Manager will contact you within 48 hours to schedule a vetting call. Approved partners receive preferential pricing, technical training, and project lead referrals.", "sort_order": 9, "published": 1},
		{"question": "How do I request a TDS or MSDS for a specific system?", "answer": "All current technical documents are available on request from our technical team. Contact us and we will respond within 4 hours with the relevant TDS, MSDS, and application guides.", "sort_order": 10, "published": 1},
	],
}

PRODUCTS = [
	{
		"system_code": "SYS-201",
		"system_name": "Xfloor Ultra-Build Epoxy",
		"subtitle": "High-Build Series",
		"icon": "epoxy",
		"chemistry_type": "Epoxy",
		"hero_image": "",
		"short_description": "High-build, solvent-free coatings for general manufacturing and logistics. Exceptional chemical resistance and adhesion to concrete substrates.",
		"tags": "Solvent-Free, High-Build",
		"requirements_tags": "Chemical Resistant, High Traffic",
		"sort_order": 1,
		"published": 1,
		"route": "/products/epoxy-ultra-build-201",
		"meta_title": "Xfloor Ultra-Build Epoxy 201 — High-Build Industrial Floor Coating",
		"meta_description": "Solvent-free, high-build epoxy floor coating for manufacturing and logistics. 1–4mm DFT, chemical resistant, pan-India supply.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "product",
		"schema_type": "Product", "canonical_url": "", "no_index": 0,
		"product_specs": [
			{"label": "Applied Thickness", "value": "1–4 mm", "sub_label": "DFT verified"},
			{"label": "Surface Finish", "value": "High Gloss", "sub_label": "Semi-matte available"},
			{"label": "Foot Traffic", "value": "24 hrs", "sub_label": "Full chemical: 7 days"},
			{"label": "VOC Level", "value": "<5 g/L", "sub_label": "Solvent-free formulation"},
			{"label": "Compressive Strength", "value": "≥ 60 N/mm²", "sub_label": ""},
			{"label": "Tensile Adhesion", "value": "≥ 1.5 MPa", "sub_label": "Concrete failure mode"},
			{"label": "Chemical Resistance", "value": "Oils, coolants, dilute acids", "sub_label": ""},
			{"label": "Temperature Range", "value": "-10°C to +60°C", "sub_label": "Service temperature"},
			{"label": "Pot Life", "value": "35 min @ 25°C", "sub_label": ""},
			{"label": "Shelf Life", "value": "12 months", "sub_label": "Unopened"},
			{"label": "Pack Size", "value": "5 Kg + 1 Kg / 20 Kg + 4 Kg", "sub_label": ""},
		],
		"product_benefits": [
			{"benefit_text": "Superior adhesion to concrete, steel, and screeds."},
			{"benefit_text": "Zero peeling: Bond-Prime penetrates carbonation layer."},
			{"benefit_text": "Chemical resistance to oils, coolants, and industrial solvents."},
			{"benefit_text": "Dust-free, non-porous, easy to sanitize."},
			{"benefit_text": "Low-odour, solvent-free formulation — suitable for occupied facilities."},
			{"benefit_text": "Seamless finish eliminates joint-contamination risk."},
		],
		"system_steps": [
			{"step_number": "01", "title": "Xfloor Bond-Prime", "description": "Penetrating epoxy primer with cross-linking adhesion promoter. Pull-off >1.5 MPa guaranteed."},
			{"step_number": "02", "title": "Xfloor Part A + Part B Body Coat", "description": "Stoichiometric resin-hardener mix. 2–3 mm applied DFT. The compressive strength layer."},
			{"step_number": "03", "title": "Xfloor Shield Top Coat", "description": "Aliphatic polyurethane topcoat. Scratch, UV, and chemical abrasion resistance. Surface hardness: Shore D 78."},
		],
	},
	{
		"system_code": "SYS-301",
		"system_name": "Xfloor PU Floor System",
		"subtitle": "Polyurethane Series",
		"icon": "pu",
		"chemistry_type": "PU",
		"hero_image": "",
		"short_description": "Impact-resistant and UV-stable polyurethane coatings for outdoor areas, car parks, and high-vibration zones.",
		"tags": "UV Stable, Impact Resistant",
		"requirements_tags": "UV Stable, Impact Resistant",
		"sort_order": 2,
		"published": 1,
		"route": "/products/pu-floor-system-301",
		"meta_title": "Xfloor PU Floor System 301 — UV-Stable Polyurethane Floor Coating",
		"meta_description": "Impact-resistant, UV-stable polyurethane floor coating for car parks, outdoor areas, and high-vibration industrial zones across India.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "product",
		"schema_type": "Product", "canonical_url": "", "no_index": 0,
		"product_specs": [
			{"label": "Applied Thickness", "value": "1–3 mm", "sub_label": "DFT verified"},
			{"label": "UV Resistance", "value": "Excellent", "sub_label": "Aliphatic formulation"},
			{"label": "Impact Resistance", "value": "High", "sub_label": "For vibration zones"},
			{"label": "Foot Traffic", "value": "24 hrs", "sub_label": "Full cure: 7 days"},
			{"label": "Temperature Range", "value": "-20°C to +80°C", "sub_label": "Service temperature"},
		],
		"product_benefits": [
			{"benefit_text": "UV-stable formulation — no yellowing outdoors."},
			{"benefit_text": "Superior impact and abrasion resistance for high-traffic zones."},
			{"benefit_text": "Suitable for car parks, ramps, and outdoor applications."},
			{"benefit_text": "Thermal cycling resistance for environments with temperature swings."},
			{"benefit_text": "Low VOC, environmentally safe formulation."},
		],
		"system_steps": [
			{"step_number": "01", "title": "Surface Preparation", "description": "Shot blasting or diamond grinding to CSP 3 profile. Moisture check below 75% RH."},
			{"step_number": "02", "title": "PU Base Coat", "description": "Two-component moisture-tolerant primer and body coat. Full mechanical bonding layer."},
			{"step_number": "03", "title": "Aliphatic PU Top Coat", "description": "UV-stable, scratch-resistant finish coat. Anti-skid aggregate broadcast available."},
		],
	},
	{
		"system_code": "SYS-302",
		"system_name": "Xfloor ESD Conductive",
		"subtitle": "Conductive Series",
		"icon": "esd",
		"chemistry_type": "ESD",
		"hero_image": "",
		"short_description": "Precision conductive flooring for electronics assembly lines, server rooms, and explosive storage. Surface resistivity <10⁶ Ω per IEC 61340-5-1.",
		"tags": "ESD Compliant, IEC 61340",
		"requirements_tags": "Anti-Static, ESD Compliant",
		"sort_order": 3,
		"published": 1,
		"route": "/products/esd-conductive-302",
		"meta_title": "Xfloor ESD Conductive 302 — Anti-Static Floor Coating IEC 61340",
		"meta_description": "Precision ESD conductive flooring for electronics assembly, server rooms, and cleanrooms. Surface resistivity <10⁶ Ω per IEC 61340-5-1.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "product",
		"schema_type": "Product", "canonical_url": "", "no_index": 0,
		"product_specs": [
			{"label": "Surface Resistivity", "value": "<10⁶ Ω", "sub_label": "Per IEC 61340-5-1"},
			{"label": "Applied Thickness", "value": "2–3 mm", "sub_label": "DFT verified"},
			{"label": "Conductive Layer", "value": "Copper tape grid", "sub_label": "Included in spec"},
			{"label": "Foot Traffic", "value": "24 hrs", "sub_label": "Full cure: 7 days"},
			{"label": "Cleanroom Compatible", "value": "Yes", "sub_label": "Low particle emission"},
		],
		"product_benefits": [
			{"benefit_text": "Meets IEC 61340-5-1 ESD standard — certified compliant."},
			{"benefit_text": "Grounding layout design included with every ESD project specification."},
			{"benefit_text": "Cleanroom-compatible application process."},
			{"benefit_text": "Seamless, non-porous surface — easy to clean and maintain."},
			{"benefit_text": "Suitable for server rooms, electronics assembly, and explosive storage."},
		],
		"system_steps": [
			{"step_number": "01", "title": "Substrate Preparation", "description": "Diamond grinding to CSP 3–4. Moisture and conductivity testing of substrate."},
			{"step_number": "02", "title": "Copper Tape Grounding Grid", "description": "Proprietary copper tape layout engineered to site plan. Full earthing continuity guaranteed."},
			{"step_number": "03", "title": "Conductive Epoxy System", "description": "Two-component conductive epoxy body coat over primer. Measured resistivity <10⁶ Ω post-cure."},
			{"step_number": "04", "title": "ESD Top Coat", "description": "Conductive polyurethane finish coat. Chemical resistance and hard-wearing surface."},
		],
	},
	{
		"system_code": "SYS-401",
		"system_name": "Xfloor Hygienic Series",
		"subtitle": "Food & Pharma Series",
		"icon": "hygienic",
		"chemistry_type": "Hygienic",
		"hero_image": "",
		"short_description": "Seamless, antimicrobial, coved flooring for FSSAI, HACCP, and GMP environments. Zero joints, zero contamination risk.",
		"tags": "Food-Grade, HACCP",
		"requirements_tags": "Food-Grade, Chemical Resistant",
		"sort_order": 4,
		"published": 1,
		"route": "/products/hygienic-series-401",
		"meta_title": "Xfloor Hygienic Series 401 — FSSAI & HACCP Floor Coating India",
		"meta_description": "Seamless, antimicrobial, coved floor coating for food processing and pharma. FSSAI and HACCP compliant. Zero joints, zero contamination risk.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "product",
		"schema_type": "Product", "canonical_url": "", "no_index": 0,
		"product_specs": [
			{"label": "FSSAI Compliance", "value": "Yes", "sub_label": "Documentation provided"},
			{"label": "HACCP Compliance", "value": "Yes", "sub_label": "Annex included in TDS"},
			{"label": "Antimicrobial", "value": "Yes", "sub_label": "Silver-ion additive"},
			{"label": "Coved Skirting", "value": "Standard", "sub_label": "100mm radius"},
			{"label": "Drain-Fall", "value": "Compliant", "sub_label": "1:60 slope achievable"},
		],
		"product_benefits": [
			{"benefit_text": "FSSAI and HACCP compliance documentation provided before project commencement."},
			{"benefit_text": "Antimicrobial silver-ion additive inhibits bacterial growth."},
			{"benefit_text": "Seamless coved skirting eliminates all harbourage zones."},
			{"benefit_text": "Drain-fall slope compliant — no standing water."},
			{"benefit_text": "GMP-compliant for pharmaceutical cleanrooms and processing facilities."},
			{"benefit_text": "Documented cleaning validation protocol included."},
		],
		"system_steps": [
			{"step_number": "01", "title": "Substrate Assessment", "description": "Moisture, pH, and surface profile testing. Crack repair and joint filling before coating."},
			{"step_number": "02", "title": "Hygienic Base Coat", "description": "Food-grade epoxy base coat with antimicrobial additive. Coved skirting formed at this stage."},
			{"step_number": "03", "title": "Body Coat", "description": "High-build antimicrobial body coat. Drain-fall slope built in at this stage using trowel-applied mortar."},
			{"step_number": "04", "title": "Hygienic Top Coat", "description": "Seamless, non-porous finish coat. Passes food-contact safety standards. Easy to sanitize."},
		],
	},
	{
		"system_code": "SYS-501",
		"system_name": "Xfloor Dielectric Coatings",
		"subtitle": "High-Voltage Series",
		"icon": "dielectric",
		"chemistry_type": "Dielectric",
		"hero_image": "",
		"short_description": "Safety flooring for electrical substations, switchgear rooms, and HV panels. >10¹⁰ Ω surface resistivity. Tested per IEC 61439.",
		"tags": "Dielectric, High Voltage",
		"requirements_tags": "Anti-Static, Chemical Resistant",
		"sort_order": 5,
		"published": 1,
		"route": "/products/dielectric-501",
		"meta_title": "Xfloor Dielectric 501 — High-Voltage Safety Floor Coating",
		"meta_description": "Dielectric floor coating with >10¹⁰ Ω resistance for electrical substations and switchgear rooms. Tested per IEC 61439.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "product",
		"schema_type": "Product", "canonical_url": "", "no_index": 0,
		"product_specs": [
			{"label": "Surface Resistivity", "value": ">10¹⁰ Ω", "sub_label": "Per IEC 61439"},
			{"label": "Applied Thickness", "value": "2–4 mm", "sub_label": "DFT verified"},
			{"label": "Dielectric Strength", "value": "High", "sub_label": "HV panel safe"},
			{"label": "Chemical Resistance", "value": "Oils, acids, alkalis", "sub_label": ""},
			{"label": "Test Standard", "value": "IEC 61439", "sub_label": "Certificate provided"},
		],
		"product_benefits": [
			{"benefit_text": ">10¹⁰ Ω surface resistivity — verified by IEC 61439 testing."},
			{"benefit_text": "Safety flooring for HV switchgear rooms and electrical substations."},
			{"benefit_text": "Test certificate and compliance documentation provided."},
			{"benefit_text": "Chemical and oil resistant — suitable for transformer bays."},
			{"benefit_text": "Seamless, no-joint surface eliminates tracking risk."},
		],
		"system_steps": [
			{"step_number": "01", "title": "Surface Preparation", "description": "Diamond grinding to CSP 3. All metal fixtures earthed and isolated before application."},
			{"step_number": "02", "title": "Dielectric Primer", "description": "Non-conductive penetrating primer. Zero conductivity path to substrate."},
			{"step_number": "03", "title": "Dielectric Body Coat", "description": "High-build dielectric epoxy body coat. Resistivity measured per layer."},
			{"step_number": "04", "title": "Dielectric Top Coat", "description": "Hard-wearing, chemical-resistant dielectric finish. IEC 61439 test certificate issued post-cure."},
		],
	},
]

INDUSTRIES = [
	{
		"name": "automotive",
		"industry_name": "Automotive",
		"description": "Engine oil and coolant resistance, heavy fork-lift traffic rating, anti-skid aggregate for ramp areas. Typical thickness: 2–4 mm.",
		"sort_order": 1, "published": 1, "route": "/industries/automotive",
		"meta_title": "Industrial Floor Coatings for Automotive Plants — Xfloor",
		"meta_description": "Epoxy and PU floor coatings for engine bays, paint shops, and chassis assembly. Fork-lift rated, chemical resistant, 2–4mm DFT.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "Epoxy Systems", "sort_order": 1},
			{"tag_text": "PU Top Coat", "sort_order": 2},
			{"tag_text": "Chemical Resistant", "sort_order": 3},
			{"tag_text": "Fork-Lift Rated", "sort_order": 4},
		],
		"recommended_systems": [{"product_system": "SYS-201"}, {"product_system": "SYS-301"}],
	},
	{
		"name": "food-processing",
		"industry_name": "Food Processing",
		"description": "FSSAI and HACCP-compliant coved flooring. Antimicrobial additive, seamless substrate with no harbourage zones. Drain-fall compliant.",
		"sort_order": 2, "published": 1, "route": "/industries/food-processing",
		"meta_title": "FSSAI & HACCP Floor Coatings for Food Processing Plants — Xfloor",
		"meta_description": "Seamless, antimicrobial coved flooring for food factories. FSSAI and HACCP compliant. No joints, no contamination risk.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "Hygienic Series", "sort_order": 1},
			{"tag_text": "FSSAI Compliant", "sort_order": 2},
			{"tag_text": "HACCP", "sort_order": 3},
			{"tag_text": "Coved Skirting", "sort_order": 4},
		],
		"recommended_systems": [{"product_system": "SYS-401"}],
	},
	{
		"name": "electronics-esd",
		"industry_name": "Electronics & ESD",
		"description": "Surface resistivity <10⁶ Ω per IEC 61340-5-1. Grounding layout engineering included with specification. Cleanroom-compatible application.",
		"sort_order": 3, "published": 1, "route": "/industries/electronics-esd",
		"meta_title": "ESD Conductive Floor Coatings for Electronics & Cleanrooms — Xfloor",
		"meta_description": "IEC 61340-5-1 compliant ESD flooring for electronics assembly, cleanrooms, and server rooms. Grounding layout design included.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "ESD Flooring", "sort_order": 1},
			{"tag_text": "IEC 61340", "sort_order": 2},
			{"tag_text": "Conductive", "sort_order": 3},
			{"tag_text": "Cleanroom", "sort_order": 4},
		],
		"recommended_systems": [{"product_system": "SYS-302"}],
	},
	{
		"name": "pharmaceuticals",
		"industry_name": "Pharmaceuticals",
		"description": "GMP-compliant seamless coating with documented cleaning validation. Passes 21 CFR Part 211 facility requirements.",
		"sort_order": 4, "published": 1, "route": "/industries/pharmaceuticals",
		"meta_title": "GMP Floor Coatings for Pharmaceutical Manufacturing — Xfloor",
		"meta_description": "GMP-compliant seamless floor coatings for pharma. Documented cleaning validation, 21 CFR Part 211 compliant.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "GMP Compliant", "sort_order": 1},
			{"tag_text": "Seamless", "sort_order": 2},
			{"tag_text": "Chemical Resistant", "sort_order": 3},
			{"tag_text": "Non-Dusting", "sort_order": 4},
		],
		"recommended_systems": [{"product_system": "SYS-401"}],
	},
	{
		"name": "warehousing-logistics",
		"industry_name": "Warehousing & Logistics",
		"description": "High-build, high-abrasion epoxy for 10T+ forklift traffic. Defined traffic lane markings with epoxy paint system.",
		"sort_order": 5, "published": 1, "route": "/industries/warehousing-logistics",
		"meta_title": "Industrial Floor Coatings for Warehouses & Logistics Hubs — Xfloor",
		"meta_description": "High-build epoxy floor coatings for warehouses. 10T+ forklift rated, traffic lane markings, abrasion resistant. Pan-India supply.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "Epoxy Systems", "sort_order": 1},
			{"tag_text": "High Build", "sort_order": 2},
			{"tag_text": "Traffic Marking", "sort_order": 3},
			{"tag_text": "Abrasion Resistant", "sort_order": 4},
		],
		"recommended_systems": [{"product_system": "SYS-201"}],
	},
	{
		"name": "electrical-substations",
		"industry_name": "Electrical Substations",
		"description": "Dielectric coatings with >10¹⁰ Ω resistance for switchgear rooms and HV areas. Tested per IEC 61439 facility requirements.",
		"sort_order": 6, "published": 1, "route": "/industries/electrical-substations",
		"meta_title": "Dielectric Floor Coatings for Electrical Substations — Xfloor",
		"meta_description": "High-voltage safety floor coatings for substations and switchgear rooms. >10¹⁰ Ω surface resistivity, IEC 61439 tested.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "Dielectric", "sort_order": 1},
			{"tag_text": "High Voltage", "sort_order": 2},
			{"tag_text": "Safety", "sort_order": 3},
			{"tag_text": "IEC 61439", "sort_order": 4},
		],
		"recommended_systems": [{"product_system": "SYS-501"}],
	},
	{
		"name": "cold-storage",
		"industry_name": "Cold Storage",
		"description": "Low-temperature cure epoxy system with thermal cycling resistance. Applied at substrate temp ≥ 5°C.",
		"sort_order": 7, "published": 1, "route": "/industries/cold-storage",
		"meta_title": "Floor Coatings for Cold Storage & Chiller Rooms — Xfloor",
		"meta_description": "Low-temperature cure epoxy for cold stores and chiller rooms. Thermal cycling resistant. Applied at substrate temp ≥ 5°C.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "Low Temp Cure", "sort_order": 1},
			{"tag_text": "Thermal Cycling", "sort_order": 2},
			{"tag_text": "Non-Slip", "sort_order": 3},
		],
		"recommended_systems": [{"product_system": "SYS-201"}],
	},
	{
		"name": "data-centres",
		"industry_name": "Data Centres",
		"description": "ESD-compliant raised-floor surrounds and server room floor. Fully conductive system with copper tape grounding grid.",
		"sort_order": 8, "published": 1, "route": "/industries/data-centres",
		"meta_title": "ESD Floor Coatings for Data Centres & Server Rooms — Xfloor",
		"meta_description": "Conductive ESD floor coatings for data centres. Raised-floor surrounds, server room floors, copper tape grounding grid included.",
		"og_title": "", "og_description": "", "og_image": "", "og_type": "website",
		"schema_type": "BreadcrumbList", "canonical_url": "", "no_index": 0,
		"spec_tags": [
			{"tag_text": "ESD Compliant", "sort_order": 1},
			{"tag_text": "Conductive", "sort_order": 2},
			{"tag_text": "Seamless", "sort_order": 3},
			{"tag_text": "Copper Grounding", "sort_order": 4},
		],
		"recommended_systems": [{"product_system": "SYS-302"}],
	},
]

TESTIMONIALS = [
	{
		"author": "VP – Operations",
		"role_and_company": "Tier-1 Automotive Supplier, Pune",
		"quote": "Xfloor's ability to coordinate material supply and expert application across our multiple manufacturing sites was impressive. They are our go-to specification for industrial coatings.",
		"system_used": "SYS-201",
		"star_rating": 5,
		"published": 1,
	},
	{
		"author": "Principal Industrial Architect",
		"role_and_company": "Design Firm, Mumbai",
		"quote": "Specifications matter. Xfloor provides the technical documentation, test certificates, and system data sheets we need to approve a flooring specification on any project.",
		"system_used": "SYS-301",
		"star_rating": 5,
		"published": 1,
	},
	{
		"author": "Head – Projects & Infrastructure",
		"role_and_company": "Food Processing Conglomerate",
		"quote": "We specified Xfloor Hygienic Series for our new Gujarat plant. FSSAI compliance documentation was provided before project commencement. Application was seamless.",
		"system_used": "SYS-401",
		"star_rating": 5,
		"published": 1,
	},
	{
		"author": "Facilities Manager",
		"role_and_company": "Data Centre, Bengaluru",
		"quote": "The ESD flooring in our server room now meets IEC 61340-5-1 standards. Xfloor provided grounding layout design as part of the system spec — no other vendor did that.",
		"system_used": "SYS-302",
		"star_rating": 5,
		"published": 1,
	},
]

GALLERY_ITEMS = [
	{"caption": "Assembly bay floor — PU 301 + Anti-skid aggregate", "sector": "Automotive", "project_image": "", "sort_order": 1, "published": 1},
	{"caption": "Paint shop floor — Epoxy 201 solvent-free", "sector": "Automotive", "project_image": "", "sort_order": 2, "published": 1},
	{"caption": "Ramp coating — Epoxy 202 with line marking", "sector": "Automotive", "project_image": "", "sort_order": 3, "published": 1},
	{"caption": "Chassis workshop — 4mm high-build epoxy", "sector": "Automotive", "project_image": "", "sort_order": 4, "published": 1},
	{"caption": "Spare parts store — Epoxy with traffic lanes", "sector": "Automotive", "project_image": "", "sort_order": 5, "published": 1},
	{"caption": "Wash bay — Coved skirting + drain seal", "sector": "Automotive", "project_image": "", "sort_order": 6, "published": 1},
	{"caption": "Chiller room floor — Hygienic 401", "sector": "Food Processing", "project_image": "", "sort_order": 1, "published": 1},
	{"caption": "Processing hall — HACCP coved skirting", "sector": "Food Processing", "project_image": "", "sort_order": 2, "published": 1},
	{"caption": "Dairy plant — Antimicrobial seamless system", "sector": "Food Processing", "project_image": "", "sort_order": 3, "published": 1},
	{"caption": "Bakery floor — Drain-fall slope + epoxy", "sector": "Food Processing", "project_image": "", "sort_order": 4, "published": 1},
	{"caption": "Cold store surround — Thermal cycling system", "sector": "Food Processing", "project_image": "", "sort_order": 5, "published": 1},
	{"caption": "Packaging area — Food-grade PU coat", "sector": "Food Processing", "project_image": "", "sort_order": 6, "published": 1},
	{"caption": "Server room ESD — IEC 61340 conductive", "sector": "High-Tech Labs", "project_image": "", "sort_order": 1, "published": 1},
	{"caption": "Electronics assembly — Conductive tile system", "sector": "High-Tech Labs", "project_image": "", "sort_order": 2, "published": 1},
	{"caption": "Cleanroom floor — ESD + low particle", "sector": "High-Tech Labs", "project_image": "", "sort_order": 3, "published": 1},
	{"caption": "HV substation — Dielectric 501 coating", "sector": "High-Tech Labs", "project_image": "", "sort_order": 4, "published": 1},
	{"caption": "Battery lab — Chemical resistant cove", "sector": "High-Tech Labs", "project_image": "", "sort_order": 5, "published": 1},
	{"caption": "R&D area — Anti-static seamless", "sector": "High-Tech Labs", "project_image": "", "sort_order": 6, "published": 1},
	{"caption": "Distribution centre — 3mm high-build epoxy", "sector": "Warehousing", "project_image": "", "sort_order": 1, "published": 1},
	{"caption": "Cold chain facility — Low temp cure epoxy", "sector": "Warehousing", "project_image": "", "sort_order": 2, "published": 1},
	{"caption": "AGV floor — Precision flatness FR4", "sector": "Warehousing", "project_image": "", "sort_order": 3, "published": 1},
	{"caption": "Racking area with line marking", "sector": "Warehousing", "project_image": "", "sort_order": 4, "published": 1},
	{"caption": "Loading dock — Anti-skid ramp system", "sector": "Warehousing", "project_image": "", "sort_order": 5, "published": 1},
	{"caption": "High-bay store — Dust-free sealer", "sector": "Warehousing", "project_image": "", "sort_order": 6, "published": 1},
	{"caption": "GMP clean room — Hygienic 401 system", "sector": "Pharmaceuticals", "project_image": "", "sort_order": 1, "published": 1},
	{"caption": "API manufacturing — Chemical resistant coat", "sector": "Pharmaceuticals", "project_image": "", "sort_order": 2, "published": 1},
	{"caption": "QC laboratory — ESD conductive flooring", "sector": "Pharmaceuticals", "project_image": "", "sort_order": 3, "published": 1},
	{"caption": "Corridor — Non-dusting seamless epoxy", "sector": "Pharmaceuticals", "project_image": "", "sort_order": 4, "published": 1},
	{"caption": "Dispensary — Antimicrobial PU", "sector": "Pharmaceuticals", "project_image": "", "sort_order": 5, "published": 1},
	{"caption": "Cold storage — Low temp cure system", "sector": "Pharmaceuticals", "project_image": "", "sort_order": 6, "published": 1},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_singleton(doctype: str, data: dict) -> None:
	doc = frappe.get_single(doctype)
	doc.update(data)
	doc.save(ignore_permissions=True)
	print(f"  saved singleton  {doctype}")


def _upsert_by_name(doctype: str, name: str, data: dict) -> None:
	if frappe.db.exists(doctype, name):
		doc = frappe.get_doc(doctype, name)
		doc.update(data)
	else:
		doc = frappe.new_doc(doctype)
		doc.update(data)
	doc.save(ignore_permissions=True)
	print(f"  upserted  {doctype}/{name}")


def _upsert_by_field(doctype: str, unique_field: str, data: dict) -> None:
	existing = frappe.db.get_value(doctype, {unique_field: data[unique_field]}, "name")
	if existing:
		doc = frappe.get_doc(doctype, existing)
		doc.update(data)
	else:
		doc = frappe.new_doc(doctype)
		doc.update(data)
	doc.save(ignore_permissions=True)
	label = str(data[unique_field])[:60]
	print(f"  upserted  {doctype} [{unique_field}={label!r}]")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run() -> None:
	print("\n=== Xfloor CMS Seed ===")

	print("\n--- Singleton Pages ---")
	_upsert_singleton("XF Site Settings", SITE_SETTINGS)
	_upsert_singleton("XF Home Page", HOME_PAGE)
	_upsert_singleton("XF About Page", ABOUT_PAGE)
	_upsert_singleton("XF Applicator Page", APPLICATOR_PAGE)
	_upsert_singleton("XF Contact Page", CONTACT_PAGE)
	_upsert_singleton("XF FAQ Page", FAQ_PAGE)

	print("\n--- Product Systems ---")
	for p in PRODUCTS:
		_upsert_by_name("XF Product System", p["system_code"], p)

	print("\n--- Industry Profiles ---")
	for ind in INDUSTRIES:
		_upsert_by_name("XF Industry Profile", ind["name"], ind)

	print("\n--- Testimonials ---")
	for t in TESTIMONIALS:
		_upsert_by_field("XF Testimonial", "author", t)

	print("\n--- Gallery Items ---")
	for g in GALLERY_ITEMS:
		_upsert_by_field("XF Gallery Item", "caption", g)

	frappe.db.commit()
	print("\nDone — all records committed.\n")
