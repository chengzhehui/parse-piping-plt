"""Stable project paths shared by conversion, diagnostics and regression tests."""
from pathlib import Path
import os

REPOSITORY = Path(__file__).resolve().parents[3]
WORKSPACE = REPOSITORY.parent
AUDIT = Path(os.environ.get('PLT_AUDIT_DIR',str(REPOSITORY / '运行记录'))).resolve()
ARCHIVE = REPOSITORY / '历史运行结果/archive/2026-10-29'
HISTORICAL_SAMPLES = ARCHIVE / 'samples_and_outputs'
