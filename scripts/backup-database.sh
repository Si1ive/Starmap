#!/bin/bash
# StarMap 数据库自动备份脚本
# 使用方法: ./scripts/backup-database.sh [backup_dir]

set -e

# 配置
BACKUP_DIR=${1:-"./backups"}
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30  # 保留30天备份

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 StarMap 数据库备份${NC}"
echo "======================"
echo "备份时间: $(date)"
echo "备份目录: $BACKUP_DIR"
echo ""

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 检查Docker是否运行
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker 未运行，请启动 Docker 后再执行备份${NC}"
    exit 1
fi

# 检查容器是否运行
check_container() {
    local container_name=$1
    if docker ps --format "{{.Names}}" | grep -q "^${container_name}$"; then
        return 0
    else
        return 1
    fi
}

# 备份 MySQL
backup_mysql() {
    echo -e "${YELLOW}📦 备份 MySQL...${NC}"
    
    if check_container "starmap-mysql"; then
        docker exec starmap-mysql mysqldump \
            -u root \
            -pstarmap_root_123 \
            --single-transaction \
            --routines \
            --triggers \
            --databases starmap \
            > "$BACKUP_DIR/mysql_${DATE}.sql" 2>/dev/null
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✅ MySQL 备份成功${NC}"
            ls -lh "$BACKUP_DIR/mysql_${DATE}.sql"
        else
            echo -e "${RED}❌ MySQL 备份失败${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  MySQL 容器未运行，跳过备份${NC}"
    fi
    echo ""
}

# 备份 Neo4j
backup_neo4j() {
    echo -e "${YELLOW}🕸️  备份 Neo4j...${NC}"
    
    if check_container "starmap-neo4j"; then
        # 创建临时备份目录
        docker exec starmap-neo4j mkdir -p /tmp/backup
        
        # 执行备份
        docker exec starmap-neo4j neo4j-admin database dump neo4j --to-path=/tmp/backup 2>/dev/null || true
        
        # 复制备份文件
        docker cp starmap-neo4j:/tmp/backup/neo4j.dump "$BACKUP_DIR/neo4j_${DATE}.dump" 2>/dev/null || \
        docker exec starmap-neo4j tar czf /tmp/neo4j_backup.tar.gz -C /data . && \
        docker cp starmap-neo4j:/tmp/neo4j_backup.tar.gz "$BACKUP_DIR/neo4j_${DATE}.tar.gz"
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✅ Neo4j 备份成功${NC}"
            ls -lh "$BACKUP_DIR/neo4j_${DATE}".*
        else
            echo -e "${RED}❌ Neo4j 备份失败${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Neo4j 容器未运行，跳过备份${NC}"
    fi
    echo ""
}

# 备份 Redis
backup_redis() {
    echo -e "${YELLOW}🔴 备份 Redis...${NC}"
    
    if check_container "starmap-redis"; then
        # 触发BGSAVE
        docker exec starmap-redis redis-cli BGSAVE > /dev/null 2>&1
        
        # 等待保存完成
        sleep 2
        
        # 复制RDB文件
        docker cp starmap-redis:/data/dump.rdb "$BACKUP_DIR/redis_${DATE}.rdb" 2>/dev/null
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✅ Redis 备份成功${NC}"
            ls -lh "$BACKUP_DIR/redis_${DATE}.rdb"
        else
            echo -e "${RED}❌ Redis 备份失败${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Redis 容器未运行，跳过备份${NC}"
    fi
    echo ""
}

# 备份 ChromaDB
backup_chromadb() {
    echo -e "${YELLOW}📊 备份 ChromaDB...${NC}"
    
    if check_container "starmap-chromadb"; then
        docker exec starmap-chromadb tar czf /tmp/chroma_backup.tar.gz -C /chroma/chroma . 2>/dev/null
        docker cp starmap-chromadb:/tmp/chroma_backup.tar.gz "$BACKUP_DIR/chromadb_${DATE}.tar.gz" 2>/dev/null
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✅ ChromaDB 备份成功${NC}"
            ls -lh "$BACKUP_DIR/chromadb_${DATE}.tar.gz"
        else
            echo -e "${RED}❌ ChromaDB 备份失败${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  ChromaDB 容器未运行，跳过备份${NC}"
    fi
    echo ""
}

# 备份 Docker 卷（额外保护）
backup_volumes() {
    echo -e "${YELLOW}💾 备份 Docker 卷...${NC}"
    
    for volume in mysql_data neo4j_data redis_data chroma_data; do
        if docker volume ls -q | grep -q "starmap_${volume}$"; then
            docker run --rm \
                -v "starmap_${volume}:/data" \
                -v "$(pwd)/$BACKUP_DIR:/backup" \
                alpine tar czf "/backup/volume_${volume}_${DATE}.tar.gz" -C /data . 2>/dev/null
            
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}✅ 卷 starmap_${volume} 备份成功${NC}"
            else
                echo -e "${RED}❌ 卷 starmap_${volume} 备份失败${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️  卷 starmap_${volume} 不存在，跳过${NC}"
        fi
    done
    echo ""
}

# 创建备份清单
create_manifest() {
    echo -e "${YELLOW}📝 创建备份清单...${NC}"
    
    cat > "$BACKUP_DIR/backup_manifest_${DATE}.json" << EOF
{
    "backup_time": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "backup_dir": "$BACKUP_DIR",
    "files": [
$(ls -1 "$BACKUP_DIR"/*_${DATE}.* 2>/dev/null | sed 's/^/        "/;s/$/",/' | sed '$ s/,$//')
    ],
    "docker_containers": [
$(docker ps --format "{{.Names}}" | grep starmap | sed 's/^/        "/;s/$/",/' | sed '$ s/,$//')
    ]
}
EOF
    
    echo -e "${GREEN}✅ 备份清单创建成功${NC}"
    echo ""
}

# 清理旧备份
cleanup_old_backups() {
    echo -e "${YELLOW}🧹 清理旧备份（保留${RETENTION_DAYS}天）...${NC}"
    
    find "$BACKUP_DIR" -name "*.sql" -mtime +$RETENTION_DAYS -delete
    find "$BACKUP_DIR" -name "*.dump" -mtime +$RETENTION_DAYS -delete
    find "$BACKUP_DIR" -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete
    find "$BACKUP_DIR" -name "*.rdb" -mtime +$RETENTION_DAYS -delete
    find "$BACKUP_DIR" -name "*.json" -mtime +$RETENTION_DAYS -delete
    
    echo -e "${GREEN}✅ 旧备份清理完成${NC}"
    echo ""
}

# 主流程
main() {
    backup_mysql
    backup_neo4j
    backup_redis
    backup_chromadb
    backup_volumes
    create_manifest
    cleanup_old_backups
    
    echo -e "${GREEN}🎉 备份完成！${NC}"
    echo "======================"
    echo "备份文件列表:"
    ls -lh "$BACKUP_DIR"/*_${DATE}.* 2>/dev/null || echo "无备份文件"
    echo ""
    echo "备份目录: $BACKUP_DIR"
    echo "备份时间: $(date)"
}

# 执行
main
