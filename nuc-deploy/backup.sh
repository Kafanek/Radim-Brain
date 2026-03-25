#!/bin/bash
# Radim Brain — Daily Backup
BACKUP_DIR="/opt/radim/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker compose exec -T db pg_dump -U radim radim_brain > "$BACKUP_DIR/radim_${TIMESTAMP}.sql"
# Keep only last 7 days
find "$BACKUP_DIR" -name "radim_*.sql" -mtime +7 -delete
echo "✅ Backup: radim_${TIMESTAMP}.sql ($(du -h "$BACKUP_DIR/radim_${TIMESTAMP}.sql" | cut -f1))"
