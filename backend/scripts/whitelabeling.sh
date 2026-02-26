#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./backend/scripts/whitelabeling.sh [options]

Options:
  --brand <name>        New brand name shown in the app UI
  --brand-url <url>     Website URL used by the footer brand link
  --logo <path>         PNG file copied to main logo locations
  --logotype <path>     PNG file copied to main logotype locations
  --favicon <path>      ICO file copied to web/public/favicon.ico
  --assets-dir <path>   Branding directory (default: assets/branding)
  --env-file <path>     Compose env file to update (default: deployment/docker_compose/.env)
  --no-env-update       Do not write NEXT_PUBLIC_BRAND_WEBSITE_URL to env-file
  --update-onyx-ico     Also copy favicon to web/public/onyx.ico
  --dry-run             Show planned changes without writing files
  -h, --help            Show this help

Example:
  ./backend/scripts/whitelabeling.sh \
    --brand "Eleven" \
    --assets-dir assets/branding \
    --dry-run

Auto-load behavior:
  If not provided explicitly, the script auto-loads files from assets-dir:
    - brand.env   -> BRAND_NAME and BRAND_WEBSITE_URL
    - brand.txt   -> brand name (legacy fallback, first non-empty line)
    - brand.url   -> brand URL (legacy fallback, first non-empty line)
    - logo.png    -> --logo
    - logotype.png-> --logotype
    - favicon.ico -> --favicon

When a brand URL is provided (via flag or brand.env), the script updates:
  NEXT_PUBLIC_BRAND_WEBSITE_URL in deployment/docker_compose/.env
EOF
}

BRAND_NAME=""
BRAND_WEBSITE_URL=""
LOGO_FILE=""
LOGOTYPE_FILE=""
FAVICON_FILE=""
ASSETS_DIR="assets/branding"
ENV_FILE="deployment/docker_compose/.env"
DRY_RUN="false"
UPDATE_ONYX_ICO="false"
NO_ENV_UPDATE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --brand)
      BRAND_NAME="${2:-}"
      shift 2
      ;;
    --brand-url)
      BRAND_WEBSITE_URL="${2:-}"
      shift 2
      ;;
    --logo)
      LOGO_FILE="${2:-}"
      shift 2
      ;;
    --logotype)
      LOGOTYPE_FILE="${2:-}"
      shift 2
      ;;
    --favicon)
      FAVICON_FILE="${2:-}"
      shift 2
      ;;
    --assets-dir)
      ASSETS_DIR="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --no-env-update)
      NO_ENV_UPDATE="true"
      shift
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --update-onyx-ico)
      UPDATE_ONYX_ICO="true"
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
ASSETS_DIR_PATH="${ASSETS_DIR}"
ENV_FILE_PATH="${ENV_FILE}"

if [[ "${ASSETS_DIR_PATH}" != /* ]]; then
  ASSETS_DIR_PATH="${REPO_ROOT}/${ASSETS_DIR_PATH}"
fi

if [[ "${ENV_FILE_PATH}" != /* ]]; then
  ENV_FILE_PATH="${REPO_ROOT}/${ENV_FILE_PATH}"
fi

require_file() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    echo "Error: file not found: $file_path" >&2
    exit 1
  fi
}

read_first_non_empty_line() {
  local file_path="$1"
  awk 'NF {print; exit}' "$file_path" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

read_env_style_value() {
  local file_path="$1"
  local key="$2"

  awk -v wanted="$key" '
    BEGIN { FS="=" }
    /^[[:space:]]*#/ { next }
    {
      line=$0
      sub(/^[[:space:]]+/, "", line)
      if (line == "") next

      split(line, parts, "=")
      current_key=parts[1]
      gsub(/[[:space:]]+$/, "", current_key)
      if (current_key != wanted) next

      value=substr(line, index(line, "=") + 1)
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)

      if (value ~ /^".*"$/ || value ~ /^'\''.*'\''$/) {
        value=substr(value, 2, length(value) - 2)
      }
      print value
      exit
    }
  ' "$file_path"
}

pick_file_from_assets_dir() {
  local output_var_name="$1"
  local candidate="$2"

  if [[ -n "${!output_var_name}" ]]; then
    return
  fi

  if [[ -f "${ASSETS_DIR_PATH}/${candidate}" ]]; then
    printf -v "$output_var_name" '%s' "${ASSETS_DIR_PATH}/${candidate}"
  fi
}

if [[ -f "${ASSETS_DIR_PATH}/brand.env" ]]; then
  if [[ -z "$BRAND_NAME" ]]; then
    BRAND_NAME="$(read_env_style_value "${ASSETS_DIR_PATH}/brand.env" "BRAND_NAME")"
  fi
  if [[ -z "$BRAND_NAME" ]]; then
    BRAND_NAME="$(read_env_style_value "${ASSETS_DIR_PATH}/brand.env" "BRAND")"
  fi
  if [[ -z "$BRAND_WEBSITE_URL" ]]; then
    BRAND_WEBSITE_URL="$(read_env_style_value "${ASSETS_DIR_PATH}/brand.env" "BRAND_WEBSITE_URL")"
  fi
fi

if [[ -z "$BRAND_NAME" && -f "${ASSETS_DIR_PATH}/brand.txt" ]]; then
  BRAND_NAME="$(read_first_non_empty_line "${ASSETS_DIR_PATH}/brand.txt")"
fi

if [[ -z "$BRAND_NAME" && -f "${REPO_ROOT}/assets/brand.txt" ]]; then
  BRAND_NAME="$(read_first_non_empty_line "${REPO_ROOT}/assets/brand.txt")"
fi

if [[ -z "$BRAND_WEBSITE_URL" && -f "${ASSETS_DIR_PATH}/brand.url" ]]; then
  BRAND_WEBSITE_URL="$(read_first_non_empty_line "${ASSETS_DIR_PATH}/brand.url")"
fi

pick_file_from_assets_dir "LOGO_FILE" "logo.png"
pick_file_from_assets_dir "LOGOTYPE_FILE" "logotype.png"
pick_file_from_assets_dir "FAVICON_FILE" "favicon.ico"

if [[ -z "$BRAND_NAME" ]]; then
  echo "Error: brand name missing." >&2
  echo "Provide --brand \"YourBrand\" or add ${ASSETS_DIR_PATH}/brand.env (BRAND_NAME=...)." >&2
  usage
  exit 1
fi

upsert_env_var() {
  local env_file_path="$1"
  local key="$2"
  local value="$3"
  local temp_file

  temp_file="$(mktemp)"

  if [[ -f "$env_file_path" ]]; then
    awk -v key="$key" -v value="$value" '
      BEGIN { updated = 0 }
      {
        if ($0 ~ "^[[:space:]]*#?[[:space:]]*" key "=") {
          if (!updated) {
            print key "=" value
            updated = 1
          }
          next
        }
        print
      }
      END {
        if (!updated) {
          print key "=" value
        }
      }
    ' "$env_file_path" > "$temp_file"
  else
    printf '%s=%s\n' "$key" "$value" > "$temp_file"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] Would set ${key} in ${env_file_path#${REPO_ROOT}/}"
    rm -f "$temp_file"
    return
  fi

  mkdir -p "$(dirname "$env_file_path")"
  mv "$temp_file" "$env_file_path"
  echo "Updated ${env_file_path#${REPO_ROOT}/}: ${key}"
}

copy_asset_to_targets() {
  local src_file="$1"
  shift

  for relative_target in "$@"; do
    local target_file="${REPO_ROOT}/${relative_target}"
    local target_dir
    target_dir="$(dirname "$target_file")"
    if [[ ! -d "$target_dir" ]]; then
      echo "Warning: target directory does not exist, skipping: $relative_target"
      continue
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
      echo "[dry-run] Would copy $src_file -> $relative_target"
    else
      cp "$src_file" "$target_file"
      echo "Copied $src_file -> $relative_target"
    fi
  done
}

replace_brand_in_file() {
  local file_path="$1"
  local temp_file
  temp_file="$(mktemp)"

  LC_ALL=C LANG=C WL_BRAND="$BRAND_NAME" perl -0pe '
    s/\bOnyx\b/$ENV{WL_BRAND}/g;
    s/\bONYX\b/uc($ENV{WL_BRAND})/ge;
  ' "$file_path" > "$temp_file"

  if cmp -s "$file_path" "$temp_file"; then
    rm -f "$temp_file"
    return
  fi

  local display_path="${file_path#${REPO_ROOT}/}"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] Would update $display_path"
    rm -f "$temp_file"
  else
    mv "$temp_file" "$file_path"
    echo "Updated $display_path"
  fi
}

collect_text_targets() {
  find \
    "${REPO_ROOT}/web/src" \
    "${REPO_ROOT}/desktop/src" \
    "${REPO_ROOT}/extensions/chrome/src" \
    "${REPO_ROOT}/widget/src" \
    -type f \
    \( -name "*.tsx" -o -name "*.ts" -o -name "*.jsx" -o -name "*.js" -o -name "*.html" -o -name "*.css" -o -name "*.md" \) \
    ! -path "*/__tests__/*" \
    ! -name "*.test.ts" \
    ! -name "*.test.tsx" \
    ! -name "*.spec.ts" \
    ! -name "*.spec.tsx" \
    -print
}

echo "White-labeling with brand name: $BRAND_NAME"
echo "Branding assets directory: ${ASSETS_DIR_PATH}"
if [[ -n "$BRAND_WEBSITE_URL" ]]; then
  echo "Brand website URL: ${BRAND_WEBSITE_URL}"
else
  echo "No brand website URL provided/found. Keeping current NEXT_PUBLIC_BRAND_WEBSITE_URL."
fi
if [[ "$DRY_RUN" == "true" ]]; then
  echo "Mode: dry-run (no files will be modified)"
fi

if [[ -n "$LOGO_FILE" ]]; then
  echo "Using logo: ${LOGO_FILE}"
else
  echo "No logo provided/found. Skipping logo copy."
fi

if [[ -n "$LOGOTYPE_FILE" ]]; then
  echo "Using logotype: ${LOGOTYPE_FILE}"
else
  echo "No logotype provided/found. Skipping logotype copy."
fi

if [[ -n "$FAVICON_FILE" ]]; then
  echo "Using favicon: ${FAVICON_FILE}"
else
  echo "No favicon provided/found. Skipping favicon copy."
fi

if [[ -n "$LOGO_FILE" ]]; then
  require_file "$LOGO_FILE"
  copy_asset_to_targets "$LOGO_FILE" \
    "web/public/logo.png" \
    "web/public/logo-dark.png" \
    "backend/static/images/logo.png" \
    "extensions/chrome/public/logo.png" \
    "widget/public/logo.png"
fi

if [[ -n "$LOGOTYPE_FILE" ]]; then
  require_file "$LOGOTYPE_FILE"
  copy_asset_to_targets "$LOGOTYPE_FILE" \
    "web/public/logotype.png" \
    "web/public/logotype-dark.png" \
    "backend/static/images/logotype.png"
fi

if [[ -n "$FAVICON_FILE" ]]; then
  require_file "$FAVICON_FILE"
  copy_asset_to_targets "$FAVICON_FILE" "web/public/favicon.ico"

  if [[ "$UPDATE_ONYX_ICO" == "true" ]]; then
    copy_asset_to_targets "$FAVICON_FILE" "web/public/onyx.ico"
  fi
fi

if [[ -n "$BRAND_WEBSITE_URL" && "$NO_ENV_UPDATE" != "true" ]]; then
  upsert_env_var "$ENV_FILE_PATH" "NEXT_PUBLIC_BRAND_WEBSITE_URL" "$BRAND_WEBSITE_URL"
fi

while IFS= read -r file_path; do
  [[ -z "$file_path" ]] && continue
  replace_brand_in_file "$file_path"
done < <(collect_text_targets)

echo "White-labeling completed."
if [[ "$DRY_RUN" == "true" ]]; then
  echo "Run again without --dry-run to apply changes."
fi
