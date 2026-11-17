#!/bin/bash
# Apply the msb_lafija -> kai_viandas rename on a PostgreSQL database.
# This script does not start or stop Odoo and does not touch production by itself.
#
# Usage:
#   migrate_rename.sh <psql-connection> <database>
# Examples:
#   migrate_rename.sh "docker exec -i odoo19test-postgres psql -U odoo19test" 00Viandas
#   migrate_rename.sh "psql -U odoo" lafija
set -euo pipefail
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <psql-prefix> <database>" >&2
  exit 2
fi
PSQL_PREFIX=$1
DB=$2
HERE=$(cd "$(dirname "$0")" && pwd)
echo "Renaming msb_lafija -> kai_viandas on database: $DB"
# shellcheck disable=SC2086
$PSQL_PREFIX -d "$DB" -v ON_ERROR_STOP=1 < "$HERE/migrate_rename.sql"
echo "SQL rename finished. Next: ensure only kai_viandas is on addons_path, then:"
echo "  odoo -d $DB -u kai_viandas --stop-after-init"
