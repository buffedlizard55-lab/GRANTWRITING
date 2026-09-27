"""Keyword topic classification.

Topics are derived. A topic is assigned only when an official text field
contains a listed term. The matched terms are stored on the record so the
assignment can be checked. Unmatched records stay unclassified.
"""

from __future__ import annotations

import re
from typing import Iterable

# Longer phrases are listed before short tokens so evidence prefers them.
TOPICS: tuple[dict, ...] = (
    {
        "id": "artificial-intelligence",
        "label": "Artificial intelligence",
        "terms": (
            "artificial intelligence",
            "machine learning",
            "deep learning",
            "neural network",
            "large language model",
            "foundation model",
            "computer vision",
            "natural language processing",
        ),
    },
    {
        "id": "cybersecurity",
        "label": "Cybersecurity",
        "terms": ("cybersecurity", "cyber security", "information assurance", "zero trust", "malware", "cryptography"),
    },
    {
        "id": "quantum",
        "label": "Quantum information science",
        "terms": (
            "quantum computing",
            "quantum information",
            "quantum sensing",
            "quantum network",
            "qubit",
            "quantum",
        ),
    },
    {
        "id": "robotics",
        "label": "Robotics",
        "terms": ("robotics", "autonomous system", "unmanned aerial", "unmanned ground", "human-robot"),
    },
    {
        "id": "advanced-manufacturing",
        "label": "Advanced manufacturing",
        "terms": (
            "advanced manufacturing",
            "additive manufacturing",
            "smart manufacturing",
            "digital twin",
            "industrial robotics",
        ),
    },
    {
        "id": "semiconductors",
        "label": "Semiconductors and microelectronics",
        "terms": ("semiconductor", "microelectronic", "integrated circuit", "chip design", "photonics"),
    },
    {
        "id": "materials",
        "label": "Materials science",
        "terms": ("materials science", "metamaterial", "nanomaterial", "nanotechnology", "composite material", "metallurgy"),
    },
    {
        "id": "nuclear",
        "label": "Nuclear technology",
        "terms": ("nuclear energy", "nuclear reactor", "fusion energy", "fission", "radioisotope", "nuclear science"),
    },
    {
        "id": "energy-storage",
        "label": "Energy storage and batteries",
        "terms": ("energy storage", "battery", "hydrogen fuel", "fuel cell"),
    },
    {
        "id": "clean-energy",
        "label": "Energy",
        "terms": (
            "renewable energy",
            "solar energy",
            "wind energy",
            "geothermal",
            "clean energy",
            "power grid",
            "electric grid",
            "carbon capture",
            "carbon management",
        ),
    },
    {
        "id": "climate",
        "label": "Climate science",
        "terms": ("climate change", "climate science", "climate model", "greenhouse gas", "global warming", "climate resilience"),
    },
    {
        "id": "earth-science",
        "label": "Earth science",
        "terms": ("earth science", "geoscience", "geology", "seismolog", "volcan", "remote sensing"),
    },
    {
        "id": "ocean",
        "label": "Ocean and marine science",
        "terms": ("oceanograph", "marine science", "marine ecosystem", "coastal resilience", "sea level", "fisheries"),
    },
    {
        "id": "environment",
        "label": "Environmental science",
        "terms": ("environmental science", "ecosystem", "biodiversity", "pollution", "air quality", "water quality", "ecology"),
    },
    {
        "id": "water",
        "label": "Water resources",
        "terms": ("water resources", "hydrology", "watershed", "drinking water", "wastewater", "drought"),
    },
    {
        "id": "wildfire",
        "label": "Wildfire",
        "terms": ("wildfire", "wildland fire", "forest fire"),
    },
    {
        "id": "agriculture",
        "label": "Agriculture",
        "terms": ("agriculture", "agricultural", "crop science", "livestock", "soil health", "precision agriculture", "food system"),
    },
    {
        "id": "biotechnology",
        "label": "Biotechnology",
        "terms": ("biotechnology", "synthetic biology", "gene editing", "crispr", "bioengineering", "biomanufactur"),
    },
    {
        "id": "genomics",
        "label": "Genomics",
        "terms": ("genomic", "genome", "sequencing", "multi-omics", "proteomic"),
    },
    {
        "id": "cancer",
        "label": "Cancer research",
        "terms": ("cancer", "oncolog", "tumor", "carcinoma"),
    },
    {
        "id": "infectious-disease",
        "label": "Infectious disease",
        "terms": ("infectious disease", "pathogen", "pandemic", "vaccine", "antimicrobial", "virology", "epidemiolog"),
    },
    {
        "id": "neuroscience",
        "label": "Neuroscience",
        "terms": ("neuroscience", "neurolog", "brain research", "alzheimer", "neurodegenerat"),
    },
    {
        "id": "mental-health",
        "label": "Mental health",
        "terms": ("mental health", "psychiatr", "substance use", "opioid", "behavioral health"),
    },
    {
        "id": "biomedical",
        "label": "Biomedical research",
        "terms": (
            "biomedical",
            "clinical trial",
            "translational research",
            "public health",
            "health research",
            "medical research",
            "therapeutics",
            "diagnostics",
        ),
    },
    {
        "id": "medical-devices",
        "label": "Medical devices and imaging",
        "terms": ("medical device", "imaging", "radiology", "diagnostic device", "biomarker"),
    },
    {
        "id": "space",
        "label": "Space technology",
        "terms": ("space technology", "spacecraft", "satellite", "orbital", "astronaut", "planetary science", "heliophys"),
    },
    {
        "id": "astronomy",
        "label": "Astronomy",
        "terms": ("astronom", "astrophys", "telescope", "exoplanet", "cosmology"),
    },
    {
        "id": "aeronautics",
        "label": "Aeronautics",
        "terms": ("aeronautic", "aviation", "hypersonic", "aircraft", "advanced air mobility"),
    },
    {
        "id": "transportation",
        "label": "Transportation",
        "terms": ("transportation", "highway", "rail ", "freight", "transit", "traffic safety", "bridge"),
    },
    {
        "id": "infrastructure",
        "label": "Infrastructure",
        "terms": ("infrastructure", "structural health", "resilient infrastructure", "civil engineering"),
    },
    {
        "id": "scientific-computing",
        "label": "Scientific computing",
        "terms": (
            "scientific computing",
            "high performance computing",
            "high-performance computing",
            "supercomput",
            "computational science",
            "research computing",
        ),
    },
    {
        "id": "information-systems",
        "label": "Information systems",
        "terms": ("information system", "data science", "data management", "software engineering", "privacy-preserving"),
    },
    {
        "id": "defense",
        "label": "Defense technologies",
        "terms": ("national security", "defense technolog", "warfighter", "munitions", "c4isr", "directed energy"),
    },
    {
        "id": "homeland-security",
        "label": "Homeland security",
        "terms": ("homeland security", "border security", "disaster resilience", "emergency management"),
    },
    {
        "id": "chemistry",
        "label": "Chemistry",
        "terms": ("chemistry", "chemical engineering", "catalysis", "polymer science"),
    },
    {
        "id": "physics",
        "label": "Physics",
        "terms": ("physics", "condensed matter", "particle physics", "plasma", "optics"),
    },
    {
        "id": "mathematics",
        "label": "Mathematics",
        "terms": ("mathematics", "mathematical science", "statistics research", "applied math"),
    },
    {
        "id": "biology",
        "label": "Biology",
        "terms": ("biology", "biological science", "molecular biology", "cell biology", "microbiome"),
    },
    {
        "id": "education-research",
        "label": "Education research",
        "terms": ("education research", "stem education", "learning science", "undergraduate research", "workforce development"),
    },
    {
        "id": "social-science",
        "label": "Social and behavioral science",
        "terms": ("social science", "behavioral science", "economics research", "sociology", "political science"),
    },
    {
        "id": "arctic",
        "label": "Arctic and polar research",
        "terms": ("arctic", "antarctic", "polar research"),
    },
    {
        "id": "critical-minerals",
        "label": "Critical minerals",
        "terms": ("critical mineral", "rare earth", "mineral supply"),
    },
    {
        "id": "sensors",
        "label": "Sensors and instrumentation",
        "terms": ("sensor", "instrumentation", "metrology", "measurement science"),
    },
    {
        "id": "aging",
        "label": "Aging",
        "terms": ("aging", "ageing", "older adult", "geriatr"),
    },
    {
        "id": "one-health",
        "label": "One Health",
        "terms": ("one health", "zoonotic", "animal health", "veterinary"),
    },
)

_COMPILED: list[tuple[dict, list[tuple[str, re.Pattern[str]]]]] = []


def _compile() -> list[tuple[dict, list[tuple[str, re.Pattern[str]]]]]:
    global _COMPILED
    if _COMPILED:
        return _COMPILED
    compiled = []
    for topic in TOPICS:
        patterns = []
        for term in topic["terms"]:
            patterns.append((term, re.compile(re.escape(term), re.IGNORECASE)))
        compiled.append((topic, patterns))
    _COMPILED = compiled
    return compiled


def classify_topics(texts: Iterable[str], limit: int = 6) -> list[dict]:
    blob = "\n".join(t for t in texts if t)
    if not blob.strip():
        return []
    found = []
    for topic, patterns in _compile():
        matched = []
        for term, pattern in patterns:
            if pattern.search(blob):
                matched.append(term)
        if matched:
            found.append(
                {
                    "id": topic["id"],
                    "label": topic["label"],
                    "matched_terms": matched[:8],
                    "method": "keyword",
                }
            )
    found.sort(key=lambda item: (-len(item["matched_terms"]), item["label"]))
    return found[:limit]


def topic_label(topic_id: str) -> str:
    for topic in TOPICS:
        if topic["id"] == topic_id:
            return topic["label"]
    return topic_id
