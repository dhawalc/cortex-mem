#!/usr/bin/env bash
# Prepare or execute an all-history privacy purge in a disposable bare mirror.
#
# This script never pushes. Its default mode is git-filter-repo --dry-run.
# Dhawal must explicitly pass --execute to rewrite the mirror, review the
# resulting refs, and separately authorize any force-push and tag replacement.
set -Eeuo pipefail

usage() {
    printf 'usage: %s <bare-mirror-path> [--execute]\n' "$0" >&2
    exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage
MIRROR_REPO="$1"
MODE="${2:---dry-run}"
[[ "$MODE" == "--dry-run" || "$MODE" == "--execute" ]] || usage
[[ -d "$MIRROR_REPO" ]] || {
    printf 'error: mirror does not exist: %s\n' "$MIRROR_REPO" >&2
    exit 2
}
[[ "$(git -C "$MIRROR_REPO" rev-parse --is-bare-repository)" == "true" ]] || {
    printf 'error: refuse to rewrite a non-bare repository\n' >&2
    exit 2
}
command -v git-filter-repo >/dev/null || {
    printf 'error: git-filter-repo is required\n' >&2
    exit 2
}

REPLACEMENTS="$(mktemp "${TMPDIR:-/tmp}/aoms-history-replacements.XXXXXX")"
cleanup() {
    rm -f -- "$REPLACEMENTS"
}
trap cleanup EXIT

# Obfuscate the match expressions themselves so scanning this script does not
# reproduce the private identifiers it is designed to remove.
printf '%s\n' \
    'regex:178[.]156[.]239[.]16==>192.0.2.10' \
    'regex:100[.]120[.]89[.]37==>192.0.2.11' \
    'regex:r[o]ot@==>backup@' \
    'regex:/home/dh[a]wal==>/home/example' \
    > "$REPLACEMENTS"

BEFORE_COMMITS="$(git -C "$MIRROR_REPO" rev-list --all --count)"
BEFORE_TAG_OBJECT="$(git -C "$MIRROR_REPO" rev-parse refs/tags/v2.0.0 2>/dev/null || true)"
BEFORE_TAG_TARGET="$(git -C "$MIRROR_REPO" rev-parse 'refs/tags/v2.0.0^{}' 2>/dev/null || true)"

FILTER_ARGS=(
    --force
    --invert-paths
    --path modules/
    --path cortex/
    --path cortex_mem/
    --path service/
    --path schemas/
    --path tasks/
    --path backup_to_vps.sh
    --path install.sh
    --path Dockerfile
    --path run.py
    --path requirements.txt
    --path daemon_integration.py
    --path ingest_all_docs.py
    --path migrate_workspace.py
    --path openclaw_integration.py
    --path scripts/export_daemon_memory.py
    --path tests/test_api.py
    --path tests/test_cortex.py
    --path tests/test_integration.py
    --path tests/test_progressive_loading.py
    --replace-text "$REPLACEMENTS"
)

printf 'mode=%s\n' "$MODE"
printf 'mirror=%s\n' "$MIRROR_REPO"
printf 'commits_before=%s\n' "$BEFORE_COMMITS"
printf 'v2.0.0_tag_object_before=%s\n' "${BEFORE_TAG_OBJECT:-absent}"
printf 'v2.0.0_target_before=%s\n' "${BEFORE_TAG_TARGET:-absent}"

if [[ "$MODE" == "--dry-run" ]]; then
    git -C "$MIRROR_REPO" filter-repo --dry-run "${FILTER_ARGS[@]}"
    printf '%s\n' \
        'dry_run_only=true' \
        'refs_changed=false' \
        'review=.git/filter-repo/fast-export.filtered' \
        'force_push_required_if_executed=true' \
        'tag_replacement_required_if_executed=true'
    exit 0
fi

printf '%s\n' \
    'WARNING: rewriting the disposable mirror; this still does not push.' >&2
git -C "$MIRROR_REPO" filter-repo "${FILTER_ARGS[@]}"

AFTER_COMMITS="$(git -C "$MIRROR_REPO" rev-list --all --count)"
AFTER_TAG_OBJECT="$(git -C "$MIRROR_REPO" rev-parse refs/tags/v2.0.0 2>/dev/null || true)"
AFTER_TAG_TARGET="$(git -C "$MIRROR_REPO" rev-parse 'refs/tags/v2.0.0^{}' 2>/dev/null || true)"
printf 'commits_after=%s\n' "$AFTER_COMMITS"
printf 'v2.0.0_tag_object_after=%s\n' "${AFTER_TAG_OBJECT:-absent}"
printf 'v2.0.0_target_after=%s\n' "${AFTER_TAG_TARGET:-absent}"
printf '%s\n' \
    'push_performed=false' \
    'force_push_required=true' \
    'tag_replacement_required=true' \
    'next_step=review every rewritten ref before separately authorized push'
