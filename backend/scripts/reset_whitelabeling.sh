#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./backend/scripts/reset_whitelabeling.sh [options]

Options:
  --source <git-ref>    Git ref to restore from (default: HEAD)
  --dry-run             Show what would be restored, without modifying files
  --yes                 Skip confirmation prompt
  -h, --help            Show this help

Examples:
  # Undo local white-label changes (not committed)
  ./backend/scripts/reset_whitelabeling.sh

  # Preview restore from main
  ./backend/scripts/reset_whitelabeling.sh --source main --dry-run

  # Force restore from origin/main without prompt
  ./backend/scripts/reset_whitelabeling.sh --source origin/main --yes
EOF
}

SOURCE_REF="HEAD"
DRY_RUN="false"
ASSUME_YES="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE_REF="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --yes)
      ASSUME_YES="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Error: this script must be run inside a git repository." >&2
  exit 1
fi

if ! git rev-parse --verify "${SOURCE_REF}^{commit}" >/dev/null 2>&1; then
  echo "Error: invalid git ref: ${SOURCE_REF}" >&2
  exit 1
fi

TARGETS=(
  "web/src"
  "desktop/src"
  "extensions/chrome/src"
  "widget/src"
  "web/public/logo.png"
  "web/public/logo-dark.png"
  "web/public/logotype.png"
  "web/public/logotype-dark.png"
  "web/public/onyx.ico"
  "web/public/favicon.ico"
  "backend/static/images/logo.png"
  "backend/static/images/logotype.png"
  "extensions/chrome/public/logo.png"
  "widget/public/logo.png"
)

RESTORE_TARGETS=()
for path in "${TARGETS[@]}"; do
  if git cat-file -e "${SOURCE_REF}:${path}" 2>/dev/null; then
    RESTORE_TARGETS+=("$path")
  else
    echo "Skipping missing path in ${SOURCE_REF}: ${path}"
  fi
done

if [[ ${#RESTORE_TARGETS[@]} -eq 0 ]]; then
  echo "Nothing to restore."
  exit 0
fi

echo "Restore source: ${SOURCE_REF}"
echo "Targets:"
for path in "${RESTORE_TARGETS[@]}"; do
  echo "  - ${path}"
done

if [[ "$DRY_RUN" == "true" ]]; then
  echo
  echo "[dry-run] Command that would be executed:"
  printf 'git restore --source=%q --' "${SOURCE_REF}"
  for path in "${RESTORE_TARGETS[@]}"; do
    printf ' %q' "$path"
  done
  printf '\n'
  exit 0
fi

if [[ "$ASSUME_YES" != "true" ]]; then
  echo
  read -r -p "This will discard local changes in the paths above. Continue? [y/N] " reply
  if [[ ! "$reply" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

git restore --source="$SOURCE_REF" -- "${RESTORE_TARGETS[@]}"
echo "White-label reset completed."
