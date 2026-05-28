from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Sub-schemas (shared)
# ---------------------------------------------------------------------------

class ItemLineSchema(BaseModel):
    raw_description: str
    hsn_code: Optional[str] = None
    qty: Optional[float] = None
    uom: Optional[str] = None
    rate: Optional[float] = None  # pre-tax unit rate


class InvoiceTaxSchema(BaseModel):
    """Indian tax invoice totals — local (domestic GST) and import (customs + IGST)."""

    # Core totals in INR (required when tax block is present)
    invoice_taxable_value: float          # taxable / assessable value before GST
    invoice_gst_amount: float             # total GST: IGST + CGST + SGST + UTGST
    invoice_total_value: float            # grand total payable as printed
    invoice_currency: Optional[str] = "INR"

    # Local GST split (intra-state: CGST+SGST; inter-state: IGST; UT: CGST+UTGST)
    invoice_igst_amount: Optional[float] = None
    invoice_cgst_amount: Optional[float] = None
    invoice_sgst_amount: Optional[float] = None
    invoice_utgst_amount: Optional[float] = None
    invoice_cess_amount: Optional[float] = None   # GST compensation cess

    # Import duties (Bill of Entry / import invoices; null for pure local)
    invoice_customs_duty_amount: Optional[float] = None       # BCD
    invoice_sws_amount: Optional[float] = None                # Social Welfare Surcharge
    invoice_import_cess_amount: Optional[float] = None      # customs / import cess (not GST cess)

    # Adjustments commonly shown on Indian invoices
    invoice_discount_amount: Optional[float] = None
    invoice_freight_amount: Optional[float] = None
    invoice_round_off: Optional[float] = None                 # +/- paisa adjustment to round total

    # TCS / TDS (separate from GST)
    invoice_tcs_amount: Optional[float] = None
    invoice_tcs_rate: Optional[float] = None
    invoice_tds_amount: Optional[float] = None
    invoice_tds_rate: Optional[float] = None

    # Foreign currency (typical on import commercial invoices)
    invoice_foreign_currency: Optional[str] = None
    invoice_foreign_currency_amount: Optional[float] = None
    invoice_exchange_rate: Optional[float] = None

    invoice_other_tax_amount: Optional[float] = None
    invoice_other_tax_rate: Optional[float] = None


# ---------------------------------------------------------------------------
# Segmentation schemas (Pass 1 — page-level split)
# ---------------------------------------------------------------------------

class DocumentSegmentSchema(BaseModel):
    """One logical document identified within a (possibly multi-page) PDF upload."""
    category: Literal["Quote", "PO", "Invoice", "IGP", "Weighment Slip",
                       "Lorry Receipt", "E-Way Bill", "Payment", "Other"]
    pages: List[int]                          # 1-based page numbers belonging to this segment
    description: str                          # plain-English label, e.g. "Tax Invoice from XYZ"
    asset_description_suggestion: Optional[str] = None


class SegmentationSchema(BaseModel):
    """LLM response for the segmentation pass. Always a list; single-doc PDFs have one element."""
    segments: List[DocumentSegmentSchema]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_str_dict(v: Any) -> Dict[str, str]:
    """Coerce any dict to Dict[str, str]. Non-string values are JSON-encoded; None → ''."""
    if not isinstance(v, dict):
        return {}
    result = {}
    for k, val in v.items():
        if val is None:
            result[str(k)] = ""
        elif isinstance(val, str):
            result[str(k)] = val
        else:
            result[str(k)] = json.dumps(val, ensure_ascii=False)
    return result


# ---------------------------------------------------------------------------
# Base extraction schema
# ---------------------------------------------------------------------------

class BaseExtractionSchema(BaseModel):
    detected_category: Literal["Quote", "PO", "Invoice", "IGP", "Weighment Slip", "Lorry Receipt", "E-Way Bill", "Payment", "Other"]
    document_description: str
    extracted_date: Optional[date] = None
    extracted_ref_no: Optional[str] = None
    summary: Optional[str] = None
    extra_fields: Dict[str, str] = {}

    @field_validator("extra_fields", mode="before")
    @classmethod
    def _coerce_extra_fields(cls, v: Any) -> Dict[str, str]:
        return _coerce_str_dict(v)


# ---------------------------------------------------------------------------
# Document-type-specific schemas
# ---------------------------------------------------------------------------

class QuoteExtractionSchema(BaseExtractionSchema):
    detected_category: Literal["Quote"] = "Quote"
    purchase_type: Optional[Literal["Local", "Import"]] = None
    supplier_name: Optional[str] = None
    supplier_gstin: Optional[str] = None
    supplier_country: Optional[str] = None
    supplier_address: Optional[str] = None
    quote_total_value: Optional[float] = None
    currency: Optional[str] = None
    validity_date: Optional[date] = None
    item_lines: List[ItemLineSchema] = []


class POExtractionSchema(BaseExtractionSchema):
    detected_category: Literal["PO"] = "PO"
    purchase_type: Optional[Literal["Local", "Import"]] = None
    supplier_name: Optional[str] = None
    supplier_gstin: Optional[str] = None
    supplier_country: Optional[str] = None
    po_number: Optional[str] = None
    po_date: Optional[date] = None
    po_total_value: Optional[float] = None
    main_location: Optional[str] = None
    level_1_location: Optional[str] = None
    level_2_location: Optional[str] = None
    level_3_location: Optional[str] = None
    item_lines: List[ItemLineSchema] = []


class InvoiceExtractionSchema(BaseExtractionSchema):
    detected_category: Literal["Invoice"] = "Invoice"
    purchase_type: Optional[Literal["Local", "Import"]] = None
    gst_supply_type: Optional[Literal["Intra-State", "Inter-State", "Import", "SEZ", "Unknown"]] = None
    place_of_supply: Optional[str] = None                     # state name or code
    supplier_name: Optional[str] = None
    supplier_gstin: Optional[str] = None                      # null for foreign supplier on import
    supplier_country: Optional[str] = None                    # e.g. "Germany" for import
    buyer_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    irn: Optional[str] = None                                 # e-invoice IRN (64-char) if shown
    bill_of_entry_number: Optional[str] = None                # import / BOE reference
    bill_of_entry_date: Optional[date] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    tax: Optional[InvoiceTaxSchema] = None
    item_lines: List[ItemLineSchema] = []


class IGPExtractionSchema(BaseExtractionSchema):
    detected_category: Literal["IGP"] = "IGP"
    igp_number: Optional[str] = None
    igp_date: Optional[date] = None
    vehicle_number: Optional[str] = None
    transporter_name: Optional[str] = None
    received_by: Optional[str] = None
    item_lines: List[ItemLineSchema] = []


class GenericExtractionSchema(BaseExtractionSchema):
    detected_category: Literal["Other"] = "Other"
    generic_data_map: Dict[str, str] = {}
    summary_note: Optional[str] = None

    @field_validator("generic_data_map", mode="before")
    @classmethod
    def _coerce_generic_data_map(cls, v: Any) -> Dict[str, str]:
        return _coerce_str_dict(v)


class WeighmentSlipSchema(BaseExtractionSchema):
    """MPD's own weigh bridge / RST printout."""
    detected_category: Literal["Weighment Slip"] = "Weighment Slip"
    rst_number: Optional[str] = None
    weighment_date: Optional[date] = None
    vehicle_number: Optional[str] = None
    material: Optional[str] = None
    party_name: Optional[str] = None
    gross_weight_kg: Optional[float] = None
    tare_weight_kg: Optional[float] = None
    net_weight_kg: Optional[float] = None
    charges_total: Optional[float] = None


class LorryReceiptSchema(BaseExtractionSchema):
    """Lorry Receipt / Goods Consignment Note from transport company."""
    detected_category: Literal["Lorry Receipt"] = "Lorry Receipt"
    gcn_lr_number: Optional[str] = None
    lr_date: Optional[date] = None
    transporter_name: Optional[str] = None
    transporter_gstin: Optional[str] = None
    consignor_name: Optional[str] = None
    consignor_gstin: Optional[str] = None
    consignee_name: Optional[str] = None
    consignee_gstin: Optional[str] = None
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    vehicle_number: Optional[str] = None
    freight_type: Optional[str] = None        # TO-PAY, PAID, etc.
    total_freight_amount: Optional[float] = None
    item_description: Optional[str] = None
    actual_weight_kg: Optional[float] = None
    charged_weight_kg: Optional[float] = None
    party_bill_no: Optional[str] = None       # cross-reference to supplier invoice


class EWayBillSchema(BaseExtractionSchema):
    """GST e-Way Bill."""
    detected_category: Literal["E-Way Bill"] = "E-Way Bill"
    eway_bill_number: Optional[str] = None
    eway_bill_date: Optional[date] = None
    valid_upto: Optional[date] = None
    irn: Optional[str] = None                 # Invoice Reference Number
    doc_number: Optional[str] = None          # linked invoice / doc number
    doc_date: Optional[date] = None
    supply_type: Optional[str] = None         # Outward / Inward
    from_name: Optional[str] = None
    from_gstin: Optional[str] = None
    to_name: Optional[str] = None
    to_gstin: Optional[str] = None
    transporter_id: Optional[str] = None      # GSTIN of transporter
    transporter_name: Optional[str] = None
    vehicle_number: Optional[str] = None
    total_taxable_value: Optional[float] = None
    total_tax_amount: Optional[float] = None
    total_invoice_value: Optional[float] = None
    item_lines: List[ItemLineSchema] = []


# ---------------------------------------------------------------------------
# Payment schema (used by APR Payment pipeline)
# ---------------------------------------------------------------------------

class PaymentExtractionSchema(BaseModel):
    payment_date: Optional[date] = None
    amount_paid: Optional[float] = None
    reference_number: Optional[str] = None
    invoice_reference_in_pdf: Optional[str] = None
    remittance_narrative: Optional[str] = None
    is_matched: bool = False
    not_found: bool = False
    summary: Optional[str] = None
    extra_fields: Dict[str, str] = {}

    @field_validator("extra_fields", mode="before")
    @classmethod
    def _coerce_extra_fields(cls, v: Any) -> Dict[str, str]:
        return _coerce_str_dict(v)


# ---------------------------------------------------------------------------
# Asset label generation schema
# ---------------------------------------------------------------------------

class AssetLabelSchema(BaseModel):
    asset_label: str  # 4-8 word concise label, e.g. "20kVA UPS — Emerson" or "30KL SS Reactor, Agitator"


# ---------------------------------------------------------------------------
# Classification-only schema (first pass)
# ---------------------------------------------------------------------------

class ClassificationSchema(BaseModel):
    detected_category: Literal["Quote", "PO", "Invoice", "IGP", "Weighment Slip", "Lorry Receipt", "E-Way Bill", "Payment", "Other"]
    document_description: str
    asset_description_suggestion: Optional[str] = None


# ---------------------------------------------------------------------------
# Mapping: category → schema class
# ---------------------------------------------------------------------------

CATEGORY_SCHEMA_MAP = {
    "Quote":          QuoteExtractionSchema,
    "PO":             POExtractionSchema,
    "Invoice":        InvoiceExtractionSchema,
    "IGP":            IGPExtractionSchema,
    "Weighment Slip": WeighmentSlipSchema,
    "Lorry Receipt":  LorryReceiptSchema,
    "E-Way Bill":     EWayBillSchema,
    "Other":          GenericExtractionSchema,
}

CATEGORY_TASK_KEY_MAP = {
    "Quote":          "apr_extract_quote",
    "PO":             "apr_extract_po",
    "Invoice":        "apr_extract_invoice",
    "IGP":            "apr_extract_igp",
    "Weighment Slip": "apr_extract_weighment",
    "Lorry Receipt":  "apr_extract_lorry_receipt",
    "E-Way Bill":     "apr_extract_eway_bill",
    "Other":          "apr_extract_generic",
}
