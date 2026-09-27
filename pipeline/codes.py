"""Official Grants.gov code maps and platform scope rules.

Code labels are taken from the Grants.gov XML extract field guide:
https://www.grants.gov/help/xml-extract/

Agency grouping names are standard U.S. federal department names used only as
display labels for agency-code prefixes. A record's agency name always comes
from the source record, not from this map.

Research-agency prefixes are a platform inclusion rule, not an official
Grants.gov flag. Every included record stores the rule that included it.
"""

from __future__ import annotations

OPPORTUNITY_CATEGORY = {
    "D": "Discretionary",
    "M": "Mandatory",
    "C": "Continuation",
    "E": "Earmark",
    "O": "Other",
}

FUNDING_INSTRUMENT = {
    "G": "Grant",
    "CA": "Cooperative Agreement",
    "PC": "Procurement Contract",
    "O": "Other",
}

FUNDING_CATEGORY = {
    "ACA": "Affordable Care Act",
    "AG": "Agriculture",
    "AR": "Arts",
    "BC": "Business and Commerce",
    "CD": "Community Development",
    "CP": "Consumer Protection",
    "DPR": "Disaster Prevention and Relief",
    "ED": "Education",
    "ELT": "Employment, Labor and Training",
    "EN": "Energy",
    "ENV": "Environment",
    "FN": "Food and Nutrition",
    "HL": "Health",
    "HO": "Housing",
    "HU": "Humanities",
    "ISS": "Income Security and Social Services",
    "IS": "Information and Statistics",
    "LJL": "Law, Justice and Legal Services",
    "NR": "Natural Resources",
    "RA": "Recovery Act",
    "RD": "Regional Development",
    "RT": "Recreation and Tourism",
    "ST": "Science and Technology and other Research and Development",
    "T": "Transportation",
    "O": "Other",
}

APPLICANT_TYPE = {
    "99": "Unrestricted (any entity type below), subject to additional eligibility text",
    "00": "State governments",
    "01": "County governments",
    "02": "City or township governments",
    "04": "Special district governments",
    "05": "Independent school districts",
    "06": "Public and State controlled institutions of higher education",
    "07": "Native American tribal governments (Federally recognized)",
    "08": "Public housing authorities/Indian housing authorities",
    "11": "Native American tribal organizations (other than Federally recognized tribal governments)",
    "12": "Nonprofits having a 501(c)(3) status with the IRS, other than institutions of higher education",
    "13": "Nonprofits that do not have a 501(c)(3) status with the IRS, other than institutions of higher education",
    "20": "Private institutions of higher education",
    "21": "Individuals",
    "22": "For-profit organizations other than small businesses",
    "23": "Small businesses",
    "25": "Others (see additional eligibility text)",
}

# Display labels for top-level agency codes. Unknown codes are not renamed.
TOP_AGENCY_NAMES = {
    "NSF": "National Science Foundation",
    "HHS": "Department of Health and Human Services",
    "DOE": "Department of Energy",
    "NASA": "National Aeronautics and Space Administration",
    "DOD": "Department of Defense",
    "USDA": "Department of Agriculture",
    "DOC": "Department of Commerce",
    "EPA": "Environmental Protection Agency",
    "DHS": "Department of Homeland Security",
    "DOT": "Department of Transportation",
    "DOI": "Department of the Interior",
    "ED": "Department of Education",
    "VA": "Department of Veterans Affairs",
    "HUD": "Department of Housing and Urban Development",
    "DOJ": "Department of Justice",
    "DOL": "Department of Labor",
    "DOS": "Department of State",
    "USAID": "U.S. Agency for International Development",
    "SBA": "Small Business Administration",
    "NIST": "National Institute of Standards and Technology",
    "NOAA": "National Oceanic and Atmospheric Administration",
    "IMLS": "Institute of Museum and Library Services",
    "NEH": "National Endowment for the Humanities",
    "NEA": "National Endowment for the Arts",
    "NARA": "National Archives and Records Administration",
    "SSA": "Social Security Administration",
    "USA": "Department of the Army",
    "USN": "Department of the Navy",
    "USAF": "Department of the Air Force",
}

# Platform inclusion rule: agency-code prefixes treated as research funders.
# Matched with startswith against the official agency code, after uppercasing.
RESEARCH_AGENCY_PREFIXES = (
    "NSF",
    "NIH",
    "HHS-NIH",
    "CDC",
    "HHS-CDC",
    "FDA",
    "HHS-FDA",
    "AHRQ",
    "HHS-AHRQ",
    "NASA",
    "DARPA",
    "DOD-DARPA",
    "AFOSR",
    "DOD-AFOSR",
    "ONR",
    "DOD-ONR",
    "ARO",
    "DOD-ARO",
    "AFRL",
    "DOD-AFRL",
    "ARL",
    "DOD-ARL",
    "NRL",
    "DOD-NRL",
    "DOD-SERDP",
    "DOD-ESTCP",
    "NIFA",
    "USDA-NIFA",
    "ARS",
    "USDA-ARS",
    "DOC-NIST",
    "DOC-NOAA",
    "NIST",
    "NOAA",
    "DHS-ST",
    "DHS-S&T",
    "USGS",
    "DOI-USGS",
    "IES",
    "ED-IES",
    "DOE-SC",
    "DOE-ARPA",
    "ARPA-E",
    "DOE-BES",
    "DOE-BER",
    "DOE-ASCR",
    "VA-ORD",
    "NIJ",
    "USDOJ-NIJ",
    "USDOJ-OJP-NIJ",
)

# If the official agency name contains one of these phrases, include the record.
# Phrases are specific agency names, not topical keywords.
RESEARCH_AGENCY_NAME_PHRASES = (
    "national science foundation",
    "national institutes of health",
    "national institute of health",
    "centers for disease control",
    "food and drug administration",
    "agency for healthcare research and quality",
    "defense advanced research projects agency",
    "air force office of scientific research",
    "office of naval research",
    "army research office",
    "army research laboratory",
    "naval research laboratory",
    "national institute of food and agriculture",
    "agricultural research service",
    "national institute of standards and technology",
    "national oceanic and atmospheric administration",
    "national aeronautics and space administration",
    "office of science",
    "arpa-e",
    "advanced research projects agency",
    "u.s. geological survey",
    "united states geological survey",
    "institute of education sciences",
    "national institute of justice",
)

# High-precision research signals used only together with a grant or
# cooperative-agreement instrument, or alone for SBIR/STTR.
# Do not treat NOFO/FOA as a research signal. Those words appear on ordinary
# assistance announcements. This pattern is only used with a grant or
# cooperative-agreement instrument.
RESEARCH_TERM_PATTERN = (
    r"\b("
    r"scientific research|basic research|applied research|fundamental research|"
    r"research and development|research & development|r&d|"
    r"broad agency announcement|baa"
    r")\b"
)

SBIR_STTR_PATTERN = r"\b(SBIR|STTR)\b"

STATUS_VALUES = (
    "open",
    "upcoming",
    "closed",
    "archived",
    "canceled",
    "unknown",
    "verification_required",
    "open_program",
)

RECORD_KINDS = ("opportunity", "forecast", "program")

ALLOWED_SOURCE_HOST_SUFFIXES = (
    ".gov",
    ".mil",
    "grants.gov",
    "nsf.gov",
    "nih.gov",
    "usaspending.gov",
)
