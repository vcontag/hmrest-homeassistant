#!/bin/sh
# Baut das Installationspaket (nur custom_components/hmrest) für den Upload in den HA-Config-Ordner.
set -e
cd "$(dirname "$0")"
VERSION=$(python3 -c "import json;print(json.load(open('custom_components/hmrest/manifest.json'))['version'])")
mkdir -p dist
rm -f dist/hmrest-install-${VERSION}.zip
find custom_components -name __pycache__ -prune -exec rm -rf {} +
zip -qr dist/hmrest-install-${VERSION}.zip custom_components/hmrest
echo "dist/hmrest-install-${VERSION}.zip"
