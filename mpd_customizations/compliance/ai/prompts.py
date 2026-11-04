EVIDENCE_EXTRACT_PROMPT = """\
You read a document uploaded as compliance evidence for MPD Industries.
The user message lists open activities and registrations by id. Match the document
to one of those ids when it is the same filing or licence. Do not invent ids.
For a licence or certificate, still fill registration_type, registration_number,
valid_from, valid_to, company, and site from the document when no id matches.
site is the location the licence covers, or null when it covers the whole company.

Return ONLY valid JSON.

document_kind is one of: licence, filing_ack, notice, unrelated.
use_year is true for a period filing (a return, challan, or statement) and false
for a standing licence or certificate.

TARGET JSON:
{
  "document_kind": "licence" | "filing_ack" | "notice" | "unrelated",
  "activity_id": string or null,
  "registration_id": string or null,
  "title": string,
  "registration_type": string or null,
  "registration_number": string or null,
  "authority": string or null,
  "valid_from": "YYYY-MM-DD" or null,
  "valid_to": "YYYY-MM-DD" or null,
  "ack_no": string or null,
  "amount": number or null,
  "domain": string or null,
  "company": string or null,
  "site": string or null,
  "summary": string,
  "use_year": boolean,
  "confidence": number between 0 and 1
}
"""
