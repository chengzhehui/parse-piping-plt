"""Stable project paths shared by conversion, diagnostics and regression tests."""
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
WORKSPACE = REPOSITORY.parent
AUDIT = REPOSITORY / 'beihai_audit'
ARCHIVE = REPOSITORY / 'archive/2026-10-29'
HISTORICAL_SAMPLES = ARCHIVE / 'samples_and_outputs'
SHA_PARSER = WORKSPACE.parent / 'PCF解析/parse-piping-sha/profiles/chengda_indonesia/parser'
