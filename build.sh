#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

.venv/bin/pyinstaller --noconfirm --clean --windowed --onefile \
  --name foliomind \
  --add-data 'assets:assets' \
  paper_studio.py

echo "Build complete: $PROJECT_DIR/dist/foliomind"
