import sys
from core import run_import

# basic args check
if len(sys.argv) < 2:
    print("Usage: python import.py <spotify.csv> [--dry-run]")
    sys.exit(1)

csv_path = sys.argv[1]
dry_run = "--dry-run" in sys.argv

run_import(csv_path=csv_path, dry_run=dry_run)
