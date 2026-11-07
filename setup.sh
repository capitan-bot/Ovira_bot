#!/usr/bin/env bash
# CAPITAN VPN - setup wrapper. Run: bash setup.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
exec bash ./install.sh
