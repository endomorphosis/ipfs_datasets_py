#!/usr/bin/env bash
# Backup and Recovery Script for GraphRAG System
# Handles database backups, IPFS content backup, and disaster recovery

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Configuration
BACKUP_DIR=${BACKUP_DIR:-"$PROJECT_ROOT/backups"}
POSTGRES_URL=${POSTGRES_URL:-"postgresql://graphrag_user:password@localhost:5432/graphrag_db"}
RETENTION_DAYS=${RETENTION_DAYS:-30}
S3_BUCKET=${S3_BUCKET:-""}

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

create_backup_directory() {
    mkdir -p "$BACKUP_DIR"/{database,ipfs,config,logs}
    log_info "Backup directory created: $BACKUP_DIR"
}

backup_database() {
    log_info "Starting database backup..."
    
    timestamp=$(date +%Y%m%d_%H%M%S)
    backup_file="$BACKUP_DIR/database/graphrag_db_$timestamp.sql"
    
    # Create database backup
    if command -v pg_dump &> /dev/null; then
        pg_dump "$POSTGRES_URL" > "$backup_file"
        
        # Compress backup
        gzip "$backup_file"
        backup_file="${backup_file}.gz"
        
        log_info "Database backup created: $backup_file"
        
        # Upload to S3 if configured
        if [ ! -z "$S3_BUCKET" ] && command -v aws &> /dev/null; then
            aws s3 cp "$backup_file" "s3://$S3_BUCKET/database/"
            log_info "Database backup uploaded to S3"
        fi
    else
        log_error "pg_dump not available for database backup"
        return 1
    fi
}

backup_ipfs_content() {
    log_info "Starting IPFS content backup..."
    
    timestamp=$(date +%Y%m%d_%H%M%S)
    backup_dir="$BACKUP_DIR/ipfs/ipfs_backup_$timestamp"
    
    # Check if IPFS is available
    if command -v ipfs &> /dev/null && ipfs id &> /dev/null; then
        mkdir -p "$backup_dir"
        
        # Export important IPFS data
        ipfs pin ls > "$backup_dir/pinned_content.txt"
        ipfs repo stat > "$backup_dir/repo_stats.txt"
        
        log_info "IPFS content metadata backed up to: $backup_dir"
    else
        log_warning "IPFS not available for backup"
    fi
}

backup_configuration() {
    log_info "Backing up configuration files..."
    
    timestamp=$(date +%Y%m%d_%H%M%S)
    config_backup="$BACKUP_DIR/config/config_backup_$timestamp.tar.gz"
    
    # Backup configuration files (excluding secrets)
    tar -czf "$config_backup" \
        --exclude="*.env" \
        --exclude="*.key" \
        --exclude="*.pem" \
        -C "$PROJECT_ROOT" \
        deployments/ \
        config/ \
        docker-compose.yml \
        Dockerfile \
        pyproject.toml \
        requirements.txt 2>/dev/null || true
    
    log_info "Configuration backup created: $config_backup"
}

cleanup_old_backups() {
    log_info "Cleaning up old backups (keeping last $RETENTION_DAYS days)..."
    
    find "$BACKUP_DIR/database" -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    find "$BACKUP_DIR/ipfs" -type d -name "ipfs_backup_*" -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null || true
    find "$BACKUP_DIR/config" -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
    
    log_info "Old backups cleaned up"
}

restore_database() {
    local backup_file="$1"
    
    if [ -z "$backup_file" ] || [ ! -f "$backup_file" ]; then
        log_error "Backup file not specified or not found: $backup_file"
        return 1
    fi
    
    log_warning "This will restore the database and overwrite existing data!"
    read -p "Are you sure you want to continue? (y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Database restore cancelled"
        return 0
    fi
    
    log_info "Restoring database from: $backup_file"
    
    # Decompress if needed
    if [[ "$backup_file" == *.gz ]]; then
        temp_file=$(mktemp)
        gunzip -c "$backup_file" > "$temp_file"
        backup_file="$temp_file"
    fi
    
    # Restore database
    if command -v psql &> /dev/null; then
        psql "$POSTGRES_URL" < "$backup_file"
        log_info "Database restored successfully"
        
        # Clean up temp file
        [ ! -z "$temp_file" ] && rm -f "$temp_file"
    else
        log_error "psql not available for database restore"
        return 1
    fi
}

show_backup_status() {
    log_info "Backup Status Summary"
    echo "===================="
    
    if [ -d "$BACKUP_DIR" ]; then
        echo "Backup Directory: $BACKUP_DIR"
        
        # Database backups
        db_backups=$(find "$BACKUP_DIR/database" -name "*.sql.gz" 2>/dev/null | wc -l)
        echo "Database Backups: $db_backups"
        
        # IPFS backups
        ipfs_backups=$(find "$BACKUP_DIR/ipfs" -type d -name "ipfs_backup_*" 2>/dev/null | wc -l)
        echo "IPFS Backups: $ipfs_backups"
        
        # Config backups
        config_backups=$(find "$BACKUP_DIR/config" -name "*.tar.gz" 2>/dev/null | wc -l)
        echo "Configuration Backups: $config_backups"
        
        echo "Total Backup Size: $(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)"
    else
        echo "No backups found"
    fi
}

usage() {
    cat << EOF
GraphRAG System Backup and Recovery Script

Usage: $0 [COMMAND] [OPTIONS]

Commands:
    backup              Create full system backup
    backup-db           Backup database only
    backup-ipfs         Backup IPFS content only
    backup-config       Backup configuration only
    restore-db FILE     Restore database from backup file
    cleanup             Clean up old backups
    status              Show backup status
    help                Show this help message

Examples:
    $0 backup
    $0 restore-db /path/to/backup.sql.gz
    $0 cleanup --retention 7
EOF
}

main() {
    COMMAND="$1"
    shift || true
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
            --retention) RETENTION_DAYS="$2"; shift 2 ;;
            --s3-bucket) S3_BUCKET="$2"; shift 2 ;;
            *) log_error "Unknown option: $1"; usage; exit 1 ;;
        esac
    done
    
    case "$COMMAND" in
        "backup")
            create_backup_directory
            backup_database
            backup_ipfs_content  
            backup_configuration
            cleanup_old_backups
            ;;
        "backup-db") create_backup_directory; backup_database ;;
        "backup-ipfs") create_backup_directory; backup_ipfs_content ;;
        "backup-config") create_backup_directory; backup_configuration ;;
        "restore-db") restore_database "$1" ;;
        "cleanup") cleanup_old_backups ;;
        "status") show_backup_status ;;
        *) usage ;;
    esac
}

main "$@"