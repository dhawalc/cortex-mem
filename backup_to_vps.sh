#!/bin/bash
# Daily backup to skibidi-vps (178.156.239.16)

set -e

AOMS_ROOT="/home/dhawal/openclaw-memory"
VPS_HOST="178.156.239.16"
VPS_USER="root"
VPS_BACKUP_DIR="/root/backups/openclaw-memory"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
LOG_FILE="$AOMS_ROOT/snapshots/backup.log"

# Ensure snapshots directory exists
mkdir -p "$AOMS_ROOT/snapshots"

echo "[$TIMESTAMP] Starting AOMS backup to VPS..." | tee -a "$LOG_FILE"

# Create local snapshot first
SNAPSHOT_FILE="$AOMS_ROOT/snapshots/aoms-$TIMESTAMP.tar.gz"
echo "Creating local snapshot: $SNAPSHOT_FILE" | tee -a "$LOG_FILE"

tar -czf "$SNAPSHOT_FILE" \
    --exclude="snapshots" \
    --exclude="__pycache__" \
    --exclude="*.pyc" \
    --exclude=".git" \
    -C "$AOMS_ROOT/.." \
    openclaw-memory/

# Get snapshot size
SNAPSHOT_SIZE=$(du -h "$SNAPSHOT_FILE" | cut -f1)
echo "Snapshot created: $SNAPSHOT_SIZE" | tee -a "$LOG_FILE"

# Ensure VPS backup directory exists
ssh -o ConnectTimeout=10 "$VPS_USER@$VPS_HOST" "mkdir -p $VPS_BACKUP_DIR"

# Rsync to VPS
echo "Syncing to VPS..." | tee -a "$LOG_FILE"
rsync -avz --progress \
    "$SNAPSHOT_FILE" \
    "$VPS_USER@$VPS_HOST:$VPS_BACKUP_DIR/" \
    2>&1 | tee -a "$LOG_FILE"

# Also sync live files (for quick recovery)
echo "Syncing live files..." | tee -a "$LOG_FILE"
rsync -avz --delete \
    --exclude="snapshots" \
    --exclude="__pycache__" \
    --exclude="*.pyc" \
    --exclude=".git" \
    "$AOMS_ROOT/" \
    "$VPS_USER@$VPS_HOST:$VPS_BACKUP_DIR/live/" \
    2>&1 | tee -a "$LOG_FILE"

# Cleanup old local snapshots (keep last 7 days)
echo "Cleaning up old snapshots..." | tee -a "$LOG_FILE"
find "$AOMS_ROOT/snapshots" -name "aoms-*.tar.gz" -mtime +7 -delete

# Verify VPS has the backup
VPS_BACKUP_COUNT=$(ssh "$VPS_USER@$VPS_HOST" "ls -1 $VPS_BACKUP_DIR/aoms-*.tar.gz 2>/dev/null | wc -l")
echo "VPS backup count: $VPS_BACKUP_COUNT snapshots" | tee -a "$LOG_FILE"

FINISH_TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
echo "[$FINISH_TIMESTAMP] Backup complete!" | tee -a "$LOG_FILE"
echo "" >> "$LOG_FILE"
