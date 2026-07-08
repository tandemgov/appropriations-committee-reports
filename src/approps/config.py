"""Configuration and settings for the approps pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EXTRACTED_DIR = DATA_DIR / "extracted"
VERIFIED_DIR = DATA_DIR / "verified"
OUTPUT_DIR = DATA_DIR / "output"
REFERENCE_DIR = DATA_DIR / "reference"

# API keys
GOVINFO_API_KEY = os.getenv("GOVINFO_API_KEY", "DEMO_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Vision model configuration for House PDF extraction
# Supports: "gemini" (free tier), "anthropic" (Claude API),
#           "openai-compat" (LM Studio, ollama, vLLM, etc.),
#           "nemotron" (local Nemotron-Parse server; free, no rate limits),
#           "hybrid" (Nemotron bulk pass + Gemini only on suspect pages — ~99.5%
#                     accuracy at ~1/3 the Gemini calls)
VISION_BACKEND = os.getenv("VISION_BACKEND", "gemini")
VISION_BASE_URL = os.getenv("VISION_BASE_URL", "http://localhost:1234/v1")
VISION_MODEL = os.getenv("VISION_MODEL", "gemini-3.1-pro-preview")
VISION_API_KEY = os.getenv("VISION_API_KEY", "lm-studio")  # LM Studio default
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Gemini transport. The AI Studio API key (default) has low per-minute quotas on preview
# models; set GEMINI_VERTEX=1 to route through Vertex (the GCP model API, now branded the
# Gemini Enterprise Agent Platform), which has far higher, requestable quotas. Vertex mode
# uses Application Default Credentials (gcloud auth application-default login), not an API key.
GEMINI_VERTEX = os.getenv("GEMINI_VERTEX", "").lower() in ("1", "true", "yes")
GEMINI_VERTEX_PROJECT = os.getenv("GEMINI_VERTEX_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
GEMINI_VERTEX_LOCATION = os.getenv("GEMINI_VERTEX_LOCATION", "global")

# Nemotron-Parse server (vLLM, OpenAI-compatible). The "nemotron" and "hybrid" backends
# post page images here. Defaults to a local server; point NEMOTRON_BASE_URL at whatever
# host serves the model.
NEMOTRON_BASE_URL = os.getenv("NEMOTRON_BASE_URL", "http://localhost:8000/v1")


def gemini_client():
    """A google-genai Client, on Vertex (ADC) when GEMINI_VERTEX is set, else the AI Studio
    API key. Both serve the same Gemini models; Vertex just carries much higher rate limits.

    A per-request timeout (ms) is set so a hung call fails fast and the caller can retry,
    rather than blocking a worker indefinitely (GEMINI_TIMEOUT_MS, default 180s)."""
    from google import genai

    http_options = {"timeout": int(os.getenv("GEMINI_TIMEOUT_MS", "180000"))}
    if GEMINI_VERTEX:
        return genai.Client(
            vertexai=True,
            project=GEMINI_VERTEX_PROJECT,
            location=GEMINI_VERTEX_LOCATION,
            http_options=http_options,
        )
    return genai.Client(api_key=GEMINI_API_KEY, http_options=http_options)

# GovInfo API
GOVINFO_BASE_URL = "https://api.govinfo.gov"
GOVINFO_CONTENT_URL = "https://www.govinfo.gov/content/pkg"
GOVINFO_RATE_LIMIT = 10  # requests per second (polite limit)

# Congress range for discovery
MIN_CONGRESS = 114  # FY2016
MAX_CONGRESS = 119  # FY2026 (1st session) + FY2027 (2nd session)

# The 12 appropriations subcommittees
SUBCOMMITTEES = [
    "Agriculture",
    "Commerce-Justice-Science",
    "Defense",
    "Energy-Water",
    "Financial-Services",
    "Homeland-Security",
    "Interior-Environment",
    "Labor-HHS-Education",
    "Legislative-Branch",
    "MilCon-VA",
    "State-Foreign-Ops",
    "THUD",
]
