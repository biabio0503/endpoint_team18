#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python -m pip install -r crawling/dacon/requirements-server.txt
python -m playwright install --with-deps chromium
