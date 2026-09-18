"""Versioned jurisdiction profiles. Applicability is a documented human decision."""
PROFILES = {
    "CSRD": {
        "version": "CSRD-E1-workspace-2026-09-17",
        "label": "CSRD / ESRS sustainability dossier",
        "status": "Applicability and reporting-year legal review required",
        "notice": "The EU lists the July 2026 ESRS amendment as adopted, with entry into force subject to Official Journal publication. Confirm the applicable standard and national implementation for this entity and reporting period.",
        "checked_at": "2026-09-17",
        "sources": ["https://finance.ec.europa.eu/regulation-and-supervision/financial-services-legislation/implementing-and-delegated-acts/corporate-sustainability-reporting-directive_en", "https://www.consilium.europa.eu/en/press/press-releases/2026/02/24/council-signs-off-simplification-of-sustainability-reporting-and-due-diligence-requirements-to-boost-eu-competitiveness/"],
    },
    "SEC": {
        "version": "SEC-voluntary-dossier-2026-09-17",
        "label": "US climate disclosure preparation dossier",
        "status": "2024 climate rules stayed; rescission proposed",
        "notice": "The SEC proposed rescission on May 29, 2026. This workspace prepares a voluntary, reviewed evidence dossier; it does not assert an effective Item 1504/1505 filing obligation or submit to EDGAR. Counsel must determine applicable disclosure duties.",
        "checked_at": "2026-09-17",
        "sources": ["https://www.sec.gov/newsroom/press-releases/2026-49-sec-proposes-rescission-climate-related-disclosure-rules"],
    },
}

SECTIONS = [
    {"id": "applicability", "title": "Applicability & reporting basis", "guidance": "Identify the legal entity, reporting period, jurisdiction, applicable standard/version and counsel's applicability determination. Include why any requirements are not applicable."},
    {"id": "boundary", "title": "Organizational & operational boundary", "guidance": "State consolidation method, entities/sites covered, acquisitions, exclusions, base year and recalculation policy."},
    {"id": "materiality", "title": "Materiality assessment", "guidance": "Document the assessment method, stakeholders, material impacts, risks and opportunities; address double materiality where applicable."},
    {"id": "governance", "title": "Governance & responsibilities", "guidance": "Name accountable management and board roles, controls, approvals, competence and oversight."},
    {"id": "policies", "title": "Policies & actions", "guidance": "Describe climate policies, resourcing, actions and implementation evidence."},
    {"id": "transition", "title": "Transition plan", "guidance": "Describe the plan, assumptions, investment, dependencies and alignment assessment, or disclose the absence of a plan."},
    {"id": "targets", "title": "Targets & progress", "guidance": "Specify target boundaries, baseline, dates, measured progress and verification. Separate aspirations from achieved results."},
    {"id": "risks", "title": "Climate risks & resilience", "guidance": "Document physical and transition risks, time horizons, scenarios, assumptions, strategy and resilience assessment."},
    {"id": "financial", "title": "Financial effects", "guidance": "Explain current and anticipated effects, relevant estimates, uncertainty, methodology and links to financial statements."},
    {"id": "energy", "title": "Energy & methodology", "guidance": "Provide energy consumption/mix, methodologies, GWP basis, factor vintage, assumptions and uncertainty. Validate all units and fuel boundaries."},
    {"id": "scope3", "title": "Scope 3 completeness", "guidance": "Screen all 15 categories, document significance, inclusions/exclusions, spend price-year adjustments and supplier data quality."},
    {"id": "assurance", "title": "Assurance & sign-off evidence", "guidance": "Identify independent assurance scope, practitioner, status, report and outstanding qualifications. Attach assurance evidence; software approval is not assurance."},
]
