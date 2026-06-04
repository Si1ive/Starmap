#!/bin/bash
# StarMap 数据库恢复脚本
# 使用方法: ./scripts/restore-database.sh [backup_date]

set -e

# 配置
BACKUP_DIR=${2:-"./backups"}
DATE=${1:-"latest"}

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔄 StarMap 数据库恢复${NC}"
echo "======================"
echo "恢复时间: $(date)"
echo "备份目录: $BACKUP_DIR"
echo "备份日期: $DATE"
echo ""

# 检查Docker是否运行
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker 未运行，请启动 Docker 后再执行恢复${NC}"
    exit 1
fi

# 查找备份文件
find_backup() {
    local pattern=$1
    if [ "$DATE" = "latest" ]; then
        ls -1t $pattern 2>/dev/null | head -1
    else
        ls -1 $pattern 2>/dev/null | grep "$DATE" | head -1
    fi
}

# 恢复 MySQL
restore_mysql() {
    echo -e "${YELLOW}📦 恢复 MySQL...${NC}"
    
    local backup_file=$(find_backup "$BACKUP_DIR/mysql_*.sql")
    
    if [ -z "$backup_file" ]; then
        echo -e "${RED}❌ 未找到 MySQL 备份文件${NC}"
        return 1
    fi
    
    echo "使用备份: $backup_file"
    
    if docker ps --format "{{.Names}}" | grep -q "^starmap-mysql$"; then
        # 恢复数据
        docker exec -i starmap-mysql mysql -u root -pstarmap_root_123 < "$backup_file"
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✅ MySQL 恢复成功${NC}"
        else
            echo -e "${RED}❌ MySQL 恢复失败${NC}"
        fi
    else
        echo -e "${RED}❌ MySQL 容器未运行，无法恢复${NC}"
        echo "请先启动容器: docker-compose up -d mysql"
    fi
    echo ""
}

# 恢复 Neo4j
restore_neo4j() {
    echo -e "${YELLOW}🕸️  恢复 Neo4j...${NC}"
    
    local backup_file=$(find_backup "$BACKUP_DIR/neo4j_*.dump")
    if [ -z "$backup_file" ]; then
        backup_file=$(find_backup "$BACKUP_DIR/neo4j_*.tar.gz")
    fi
    
    if [ -z "$backup_file" ]; then
        echo -e "${RED}❌ 未找到 Neo4j 备份文件${NC}"
        return 1
    fi
    
    echo "使用备份: $backup_file"
    
    if docker ps --format "{{.Names}}" | grep -q "^starmap-neo4j$"; then
        # 停止Neo4j
        docker stop starmap-neo4j
        
        # 恢复数据
        if [[ "$backup_file" == *.dump ]]; then
            docker exec starmap-neo4j neo4j-admin database load neo4j --from-path=/tmp/backup
        else
            docker exec starmap-neo4j tar xzf /tmp/neo4j_backup.tar.gz -C /data
            docker cp "$backup_file" starmap-neo4j:/tmp/neo4j_backup.tar.gz
            docker exec starmap-neo4j tar xzf /tmp/neo4j_backup.tar.gz -C /data
        fi
        
        # 启动Neo4j
        docker start starmap-neo4j
        
        echo -e "${GREEN}✅ Neo4j 恢复成功${NC}"
    else
        echo -e "${RED}❌ Neo4j 容器未运行，无法恢复${NC}"
    fi
    echo ""
}

# 恢复 Redis
restore_redis() {
    echo -e "${YELLOW}🔴 恢复 Redis...${NC}"
    
    local backup_file=$(find_backup "$BACKUP_DIR/redis_*.rdb")
    
    if [ -z "$backup_file" ]; then
        echo -e "${RED}❌ 未找到 Redis 备份文件${NC}"
        return 1
    fi
    
    echo "使用备份: $backup_file"
    
    if docker ps --format "{{.Names}}" | grep -q "^starmap-redis$"; then
        # 停止Redis
        docker stop starmap-redis
        
        # 复制RDB文件
        docker cp "$backup_file" starmap-redis:/data/dump.rdb
        
        # 启动Redis
        docker start starmap-redis
        
        echo -e "${GREEN}✅ Redis 恢复成功${NC}"
    else
        echo -e "${RED}❌ Redis 容器未运行，无法恢复${NC}"
    fi
    echo ""
}

# 恢复 ChromaDB
restore_chromadb() {
    echo -e "${YELLOW}📊 恢复 ChromaDB...${NC}"
    
    local backup_file=$(find_backup "$BACKUP_DIR/chromadb_*.tar.gz")
    
    if [ -z "$backup_file" ]; then
        echo -e "${RED}❌ 未找到 ChromaDB 备份文件${NC}"
        return 1
    fi
    
    echo "使用备份: $backup_file"
    
    if docker ps --format "{{.Names}}" | grep -q "^starmap-chromadb$"; then
        # 停止ChromaDB
        docker stop starmap-chromadb
        
        # 恢复数据
        docker cp "$backup_file" starmap-chromadb:/tmp/chroma_backup.tar.gz
        docker exec starmap-chromadb tar xzf /tmp/chroma_backup.tar.gz -C /chroma/chroma
        
        # 启动ChromaDB
        docker start starmap-chromadb
        
        echo -e "${GREEN}✅ ChromaDB 恢复成功${NC}"
    else
        echo -e "${RED}❌ ChromaDB 容器未运行，无法恢复${NC}"
    fi
    echo ""
}

# 显示帮助
show_help() {
    echo "使用方法:"
    echo "  ./scripts/restore-database.sh [日期] [备份目录]"
    echo ""
    echo "示例:"
    echo "  ./scripts/restore-database.sh                    # 恢复最新备份"
    echo "  ./scripts/restore-database.sh 20240115           # 恢复指定日期"
    echo "  ./scripts/restore-database.sh latest ./backups   # 指定备份目录"
    echo ""
    echo "可用备份:"
    ls -1 "$BACKUP_DIR" 2>/dev/null | head -20 || echo "无备份文件"
}

# 主流程
main() {
    if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        show_help
        exit 0
    fi
    
    echo -e "${YELLOW}⚠️  警告：恢复将覆盖现有数据！${NC}"
    echo "是否继续？(yes/no)"
    read -r answer
    
    if [ "$answer" != "yes" ]; then
        echo "恢复已取消"
        exit 0
    fi
    
    restore_mysql
    restore_neo4j
    restore_redis
    restore_chromadb
    
    echo -e "${GREEN}🎉 恢复完成！${NC}"
    echo "======================"
    echo "恢复时间: $(date)"
}

# 执行
main "$@"
