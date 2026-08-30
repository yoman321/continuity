#!/usr/bin/env bash
# Install the Verify gate's launcher onto the seeded wiki as MediaWiki:Common.js.
#
# Separate from seed_wiki.py for a permissions reason, not a stylistic one: the bot's
# BotPassword carries `basic,editpage,createeditmovepage` (scripts/setup_wiki.sh) and editing
# the MediaWiki: namespace needs `editinterface`, which those grants do not include. So this
# goes through the maintenance script as the admin account instead of the API.
#
# Idempotent — re-running overwrites the page with whatever is in wiki-config/.
#
#   ./scripts/install_launcher.sh                       # -> http://localhost:8000
#   CONTINUITY_ORIGIN=https://... ./scripts/install_launcher.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/wiki-config/continuity-launcher.js"

# Read one key out of .env without sourcing it — values there are generated secrets and some
# are not shell-safe.
env_get() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

ORIGIN="${CONTINUITY_ORIGIN:-$(env_get CONTINUITY_ORIGIN)}"
ORIGIN="${ORIGIN:-http://localhost:8000}"
ADMIN="${MEDIAWIKI_ADMIN_USER:-$(env_get MEDIAWIKI_ADMIN_USER)}"
ADMIN="${ADMIN:-ContinuityAdmin}"

[ -f "$SOURCE" ] || { echo "missing: $SOURCE"; exit 1; }
[ -f "$ROOT/wiki/maintenance/run.php" ] || {
	echo "no wiki/ — run ./scripts/setup_wiki.sh first"; exit 1; }

echo "==> MediaWiki:Common.js  (origin $ORIGIN, as $ADMIN)"
sed "s|__CONTINUITY_ORIGIN__|$ORIGIN|g" "$SOURCE" \
	| php "$ROOT/wiki/maintenance/run.php" edit.php \
		--user "$ADMIN" \
		--summary "Install the Continuity Verify-gate launcher" \
		MediaWiki:Common.js

echo "installed. Hard-reload a page to clear the ResourceLoader cache:"
echo "  open 'http://localhost:8080/index.php?title=Deadpool_%26_Wolverine&action=purge'"
