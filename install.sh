#!/usr/bin/env bash
set -euo pipefail

REPO="shivakvasar/cdo-mcp-server"
BRANCH="main"

echo "Installing cdo-mcp-server from GitHub..."
pip install "git+https://github.com/${REPO}.git@${BRANCH}"

echo "✅ Done. Run: cdo-mcp-server"