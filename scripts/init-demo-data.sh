#!/bin/bash
# StarMap 演示数据初始化脚本 (Podman 版本)
# 使用方法: ./scripts/init-demo-data.sh

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🚀 StarMap 演示数据初始化${NC}"
echo "========================="
echo "时间: $(date)"
echo ""

# 检查Podman是否运行
if ! podman info > /dev/null 2>&1; then
    echo -e "${RED}❌ Podman 未运行，请先启动 Podman${NC}"
    exit 1
fi

# 检查容器是否运行
check_container() {
    podman ps --format "{{.Names}}" | grep -q "^${1}$"
}

# 等待服务就绪
wait_for_service() {
    local container=$1
    local port=$2
    local max_attempts=30
    local attempt=1
    
    echo -e "${YELLOW}⏳ 等待 $container 就绪...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if podman exec $container mysqladmin ping -h localhost -u root -pstarmap_root_123 > /dev/null 2>&1 || \
           podman exec $container wget --no-verbose --tries=1 --spider http://localhost:$port > /dev/null 2>&1 || \
           podman exec $container redis-cli ping > /dev/null 2>&1; then
            echo -e "${GREEN}✅ $container 已就绪${NC}"
            return 0
        fi
        
        echo "  尝试 $attempt/$max_attempts..."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo -e "${RED}❌ $container 启动超时${NC}"
    return 1
}

# 初始化 MySQL 数据
init_mysql_data() {
    echo -e "${YELLOW}📦 初始化 MySQL 数据...${NC}"
    
    if check_container "starmap-mysql"; then
        # 创建演示数据SQL
        cat > /tmp/demo_data.sql << 'EOF'
-- 插入演示人物数据
INSERT INTO persons (id, name, name_en, gender, birth_date, birth_place, nationality, summary, categories, status, popularity_score) VALUES
('person_001', '周杰伦', 'Jay Chou', 'male', '1979-01-18', '台湾省新北市', '中国', '华语流行乐男歌手、音乐人、演员、导演、编剧。', '["singer", "actor", "director"]', 'active', 95.5),
('person_002', '方文山', 'Vincent Fang', 'male', '1969-01-26', '台湾省花莲县', '中国', '华语流行乐作词人、导演。', '["songwriter", "director"]', 'active', 78.0),
('person_003', '林俊杰', 'JJ Lin', 'male', '1981-03-27', '新加坡', '新加坡', '华语流行乐男歌手、词曲创作人、音乐制作人。', '["singer", "songwriter", "producer"]', 'active', 88.5),
('person_004', '邓紫棋', 'G.E.M.', 'female', '1991-08-16', '上海市', '中国', '华语流行乐女歌手、词曲创作人。', '["singer", "songwriter"]', 'active', 85.0),
('person_005', '张学友', 'Jacky Cheung', 'male', '1961-07-10', '香港', '中国', '华语流行乐男歌手、演员。', '["singer", "actor"]', 'active', 92.0)
ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;

-- 插入演示作品数据
INSERT INTO works (id, title, type, release_date, genre, rating, summary, status) VALUES
('work_001', '七里香', 'album', '2004-08-03', '流行', 9.2, '周杰伦第五张录音室专辑。', 'active'),
('work_002', '叶惠美', 'album', '2003-07-31', '流行', 9.0, '周杰伦第四张录音室专辑。', 'active'),
('work_003', '江南', 'album', '2004-06-04', '流行', 8.8, '林俊杰第二张录音室专辑。', 'active'),
('work_004', '光年之外', 'single', '2016-12-30', '流行', 8.5, '邓紫棋代表作之一。', 'active')
ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;

-- 插入演示关系数据 (适配实际表结构：source_id, target_id, relation_type, properties)
INSERT INTO person_relations (source_id, target_id, relation_type, properties, confidence, source, is_verified) VALUES
('person_001', 'person_002', 'COLLABORATED_WITH', '{"description": "长期合作伙伴，共同创作多首经典歌曲", "start_date": "2000-01-01"}', 0.95, 'demo', 1),
('person_001', 'person_003', 'FRIEND', '{"description": "好友关系，同为华语乐坛重要歌手"}', 0.90, 'demo', 1),
('person_002', 'person_001', 'COLLABORATED_WITH', '{"description": "为周杰伦创作大量歌词", "start_date": "2000-01-01"}', 0.95, 'demo', 1)
ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;
EOF
        
        # 执行SQL
        podman exec -i starmap-mysql mysql -u root -pstarmap_root_123 starmap < /tmp/demo_data.sql
        
        echo -e "${GREEN}✅ MySQL 演示数据初始化完成${NC}"
        echo "  - 5个演示人物"
        echo "  - 4个演示作品"
        echo "  - 3个演示关系"
    else
        echo -e "${RED}❌ MySQL 容器未运行${NC}"
    fi
    echo ""
}

# 初始化 Neo4j 数据
init_neo4j_data() {
    echo -e "${YELLOW}🕸️  初始化 Neo4j 数据...${NC}"
    
    if check_container "starmap-neo4j"; then
        # 创建演示数据Cypher
        cat > /tmp/demo_data.cypher << 'EOF'
// 创建人物节点
CREATE (jay:Person {id: 'person_001', name: '周杰伦', name_en: 'Jay Chou', gender: 'male', birth_date: '1979-01-18', nationality: '中国', popularity_score: 95.5, categories: ['singer', 'actor', 'director'], summary: '华语流行乐男歌手、音乐人、演员、导演、编剧。'})
CREATE (fang:Person {id: 'person_002', name: '方文山', name_en: 'Vincent Fang', gender: 'male', birth_date: '1969-01-26', nationality: '中国', popularity_score: 78.0, categories: ['songwriter', 'director'], summary: '华语流行乐作词人、导演。'})
CREATE (jj:Person {id: 'person_003', name: '林俊杰', name_en: 'JJ Lin', gender: 'male', birth_date: '1981-03-27', nationality: '新加坡', popularity_score: 88.5, categories: ['singer', 'songwriter', 'producer'], summary: '华语流行乐男歌手、词曲创作人、音乐制作人。'})
CREATE (gem:Person {id: 'person_004', name: '邓紫棋', name_en: 'G.E.M.', gender: 'female', birth_date: '1991-08-16', nationality: '中国', popularity_score: 85.0, categories: ['singer', 'songwriter'], summary: '华语流行乐女歌手、词曲创作人。'})
CREATE (jacky:Person {id: 'person_005', name: '张学友', name_en: 'Jacky Cheung', gender: 'male', birth_date: '1961-07-10', nationality: '中国', popularity_score: 92.0, categories: ['singer', 'actor'], summary: '华语流行乐男歌手、演员。'})

// 创建作品节点
CREATE (album1:Work {id: 'work_001', title: '七里香', type: 'album', release_date: '2004-08-03', genre: '流行', rating: 9.2})
CREATE (album2:Work {id: 'work_002', title: '叶惠美', type: 'album', release_date: '2003-07-31', genre: '流行', rating: 9.0})

// 创建关系
CREATE (jay)-[:COLLABORATED_WITH {start_date: '2000-01-01', description: '长期合作伙伴'}]->(fang)
CREATE (fang)-[:COLLABORATED_WITH {start_date: '2000-01-01', description: '为周杰伦创作歌词'}]->(jay)
CREATE (jay)-[:FRIEND]->(jj)
CREATE (jj)-[:FRIEND]->(jay)
CREATE (jay)-[:CREATED {role: '演唱'}]->(album1)
CREATE (jay)-[:CREATED {role: '演唱'}]->(album2)
CREATE (fang)-[:CREATED {role: '作词'}]->(album1)

RETURN 'Neo4j演示数据创建完成' as result
EOF
        
        # 执行Cypher
        podman exec -i starmap-neo4j cypher-shell -u neo4j -p starmap123 < /tmp/demo_data.cypher
        
        echo -e "${GREEN}✅ Neo4j 演示数据初始化完成${NC}"
        echo "  - 5个人物节点"
        echo "  - 2个作品节点"
        echo "  - 6个关系"
    else
        echo -e "${RED}❌ Neo4j 容器未运行${NC}"
    fi
    echo ""
}

# 验证数据
verify_data() {
    echo -e "${YELLOW}🔍 验证数据...${NC}"
    
    if check_container "starmap-mysql"; then
        echo "MySQL 人物数量:"
        podman exec starmap-mysql mysql -u root -pstarmap_root_123 -e "SELECT COUNT(*) as total_persons FROM starmap.persons;" 2>/dev/null || echo "  无法查询"
    fi
    
    if check_container "starmap-neo4j"; then
        echo "Neo4j 人物数量:"
        podman exec starmap-neo4j cypher-shell -u neo4j -p starmap123 "MATCH (p:Person) RETURN count(p) as total_persons;" 2>/dev/null || echo "  无法查询"
    fi
    
    echo ""
}

# 主流程
main() {
    # 检查并启动服务
    if ! check_container "starmap-mysql" || ! check_container "starmap-neo4j"; then
        echo -e "${YELLOW}⚠️  服务未运行，尝试启动...${NC}"
        podman-compose -f docker-compose.podman.yml up -d mysql neo4j
        sleep 10
    fi
    
    # 等待服务就绪
    wait_for_service "starmap-mysql" 3306
    wait_for_service "starmap-neo4j" 7474
    
    # 初始化数据
    init_mysql_data
    init_neo4j_data
    
    # 验证
    verify_data
    
    echo -e "${GREEN}🎉 演示数据初始化完成！${NC}"
    echo "========================="
    echo "现在可以访问:"
    echo "  - 前端: http://localhost:5173"
    echo "  - 后端API: http://localhost:8000"
    echo "  - Neo4j浏览器: http://localhost:7474"
    echo ""
    echo "演示账号:"
    echo "  - 用户名: admin"
    echo "  - 密码: admin123"
}

# 执行
main