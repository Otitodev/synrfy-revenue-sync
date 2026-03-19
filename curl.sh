#!/usr/bin/env bash
# Manual sync trigger examples
# Run: bash curl.sh

BASE_URL="http://localhost:8000"

# Sync a specific date
echo "Triggering sync for 2025-08-11..."
curl -s -X POST "$BASE_URL/sync/run" \
  -H "Content-Type: application/json" \
  -d '{"date": "2025-08-11"}' | python3 -m json.tool

echo ""

# Sync today (omit date field)
echo "Triggering sync for today..."
curl -s -X POST "$BASE_URL/sync/run" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
