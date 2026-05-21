#!/bin/bash
# Code Arena - PostgreSQL 备份与恢复
set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/backups"
COMPOSE_CMD="docker compose -f docker-compose.prod.yml"
RETAIN_DAYS=30

_usage() {
    cat <<EOF
Usage: $0 <command>

Commands:
  backup    创建数据库备份
  restore   从备份恢复 (需要指定文件: RESTORE=<file> $0 restore)
  list      列出所有备份
  prune     清理超过 ${RETAIN_DAYS} 天的旧备份
EOF
    exit 1
}

_backup() {
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    FILENAME="code_arena_${TIMESTAMP}.sql.gz"

    echo "==> 开始备份..."
    $COMPOSE_CMD exec -T db pg_dump -U postgres code_arena | gzip > "$BACKUP_DIR/$FILENAME"

    SIZE=$(du -h "$BACKUP_DIR/$FILENAME" | cut -f1)
    echo "==> 备份完成: backups/$FILENAME ($SIZE)"

    _prune
}

_restore() {
    local restore_file="${RESTORE:-}"
    if [ -z "$restore_file" ]; then
        echo "错误: 需要指定备份文件"
        echo "用法: RESTORE=backups/code_arena_20260521_020000.sql.gz $0 restore"
        echo ""
        _list
        exit 1
    fi

    if [ ! -f "$restore_file" ]; then
        echo "错误: 文件不存在: $restore_file"
        exit 1
    fi

    echo "警告: 这将覆盖当前数据库中的所有数据！"
    read -rp "确认恢复 from $restore_file? [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "已取消"
        exit 0
    fi

    echo "==> 恢复中..."
    gunzip -c "$restore_file" | $COMPOSE_CMD exec -T db psql -U postgres code_arena
    echo "==> 恢复完成"
}

_list() {
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo "无备份文件"
        return
    fi
    echo "备份文件 (backups/):"
    ls -lht "$BACKUP_DIR"/*.sql.gz 2>/dev/null | awk '{printf "  %s  %s\n", $5, $9}' || echo "  (空)"
}

_prune() {
    if [ ! -d "$BACKUP_DIR" ]; then
        return
    fi
    local count
    count=$(find "$BACKUP_DIR" -name "*.sql.gz" -mtime +${RETAIN_DAYS} -print -delete 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
        echo "==> 已清理 ${count} 个超过 ${RETAIN_DAYS} 天的旧备份"
    fi
}

[ $# -lt 1 ] && _usage

case "$1" in
    backup)  _backup  ;;
    restore) _restore ;;
    list)    _list    ;;
    prune)   mkdir -p "$BACKUP_DIR"; _prune ;;
    *)       _usage   ;;
esac
