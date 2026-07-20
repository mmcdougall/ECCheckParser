from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
ORIGINALS_DIR = DATA_DIR / "originals"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
ARTIFACT_PDFS_DIR = ARTIFACTS_DIR / "pdfs"
ARTIFACT_CSV_DIR = ARTIFACTS_DIR / "csv"
ARTIFACT_CHUNKS_DIR = ARTIFACTS_DIR / "chunks"
ARTIFACT_FUND_UPDATES_DIR = ARTIFACTS_DIR / "fund_updates"
ARTIFACT_CASH_INVESTMENTS_DIR = ARTIFACTS_DIR / "cash_investments"
