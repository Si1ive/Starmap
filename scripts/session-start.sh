#!/bin/bash
# StarMap 会话启动脚本
# 用法: ./scripts/session-start.sh [backend|frontend|data|pm]

set -e

ROLE=${1:-""}
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 显示帮助
if [ -z "$ROLE" ] || [ "$ROLE" = "--help" ] || [ "$ROLE" = "-h" ]; then
    echo -e "${GREEN}StarMap 会话启动脚本${NC}"
    echo "用法: ./scripts/session-start.sh [backend|frontend|data|pm]"
    echo ""
    echo "示例:"
    echo "  ./scripts/session-start.sh backend   # 启动后端工程师会话"
    echo "  ./scripts/session-start.sh frontend  # 启动前端工程师会话"
    echo "  ./scripts/session-start.sh data      # 启动数据工程师会话"
    echo "  ./scripts/session-start.sh pm        # 启动PM会话"
    exit 0
fi

# 验证角色
if [ "$ROLE" != "backend" ] && [ "$ROLE" != "frontend" ] && [ "$ROLE" != "data" ] && [ "$ROLE" != "pm" ]; then
    echo -e "${RED}❌ 错误：未知的角色 '$ROLE'${NC}"
    echo "支持的角色: backend, frontend, data, pm"
    exit 1
fi

echo -e "${GREEN}🚀 StarMap 会话启动${NC}"
echo "=================="
echo "时间: $(date)"
echo "角色: $ROLE"
echo ""

# 1. 读取CHANGELOG
echo -e "${YELLOW}📋 步骤1: 读取最新变更日志${NC}"
echo "------------------------------"
if [ -f "CHANGELOG.md" ]; then
    # 读取最近的变更记录（非模板部分）
    sed -n '/^## 20/,/^## 模板/p' CHANGELOG.md | head -40
else
    echo -e "${RED}⚠️  CHANGELOG.md 不存在${NC}"
fi
echo ""

# 2. 读取角色定义
echo -e "${YELLOW}👤 步骤2: 读取角色定义${NC}"
echo "------------------------------"
ROLE_FILE="docs/team/${ROLE}-role.md"
if [ -f "$ROLE_FILE" ]; then
    echo -e "${BLUE}角色文件: $ROLE_FILE${NC}"
    echo ""
    # 读取角色定义前20行
    head -20 "$ROLE_FILE"
    echo ""
    echo "... (完整定义请阅读 $ROLE_FILE)"
else
    echo -e "${RED}⚠️  角色文件 $ROLE_FILE 不存在${NC}"
fi
echo ""

# 3. 读取当前任务
echo -e "${YELLOW}📌 步骤3: 读取当前任务${NC}"
echo "------------------------------"
if [ -f "$ROLE_FILE" ]; then
    # 提取当前任务部分
    grep -A 20 "当前任务" "$ROLE_FILE" || echo "未找到当前任务定义"
else
    echo "无法读取任务"
fi
echo ""

# 4. 读取路线图进度
echo -e "${YELLOW}🗺️  步骤4: 读取路线图${NC}"
echo "------------------------------"
ROADMAP_FILE="docs/roadmap/${ROLE}-roadmap.md"
if [ -f "$ROADMAP_FILE" ]; then
    echo -e "${BLUE}路线图文件: $ROADMAP_FILE${NC}"
    echo ""
    # 读取前30行
    head -30 "$ROADMAP_FILE"
else
    echo -e "${RED}⚠️  路线图文件 $ROADMAP_FILE 不存在${NC}"
fi
echo ""

# 5. 检查Git状态
echo -e "${YELLOW}📝 步骤5: 检查Git状态${NC}"
echo "------------------------------"
if [ -d ".git" ]; then
    BRANCH=$(git branch --show-current)
    echo -e "当前分支: ${BLUE}$BRANCH${NC}"
    
    # 检查是否有未提交的更改
    if ! git diff-index --quiet HEAD --; then
        echo -e "${RED}⚠️  有未提交的更改:${NC}"
        git status --short
    else
        echo -e "${GREEN}✅ 工作区干净${NC}"
    fi
else
    echo -e "${RED}⚠️  不是Git仓库${NC}"
fi
echo ""

# 6. 输出会话提示
echo -e "${GREEN}✅ 会话启动完成！${NC}"
echo "=================="
echo ""
echo -e "${YELLOW}💡 提示：${NC}"
echo "1. 请确认当前任务和优先级"
echo "2. 开始工作前，先阅读相关文档"
echo "3. 修改影响其他角色时，更新CHANGELOG.md"
echo "4. 工作完成后，提交代码并记录日志"
echo ""
echo -e "${YELLOW}📋 检查清单：${NC}"
echo "□ 了解最新变更"
echo "□ 确认当前任务"
echo "□ 检查工作区状态"
echo "□ 开始工作"
echo ""

# 输出角色特定的提示
case $ROLE in
    backend)
        echo -e "${BLUE}后端工程师专属提示：${NC}"
        echo "- API文档位置: docs/api/README.md"
        echo "- 数据库模型: docs/tech/data-model.md"
        echo "- 启动命令: docker-compose up -d mysql neo4j redis"
        ;;
    frontend)
        echo -e "${BLUE}前端工程师专属提示：${NC}"
        echo "- 接口文档: docs/api/README.md"
        echo "- 用户端: cd frontend && npm run dev"
        echo "- 管理端: cd frontend-admin && npm run dev"
        ;;
    data)
        echo -e "${BLUE}数据工程师专属提示：${NC}"
        echo "- 爬虫框架: backend/app/crawler/"
        echo "- 数据模型: docs/tech/data-model.md"
        echo "- Neo4j浏览器: http://localhost:7474"
        ;;
    pm)
        echo -e "${BLUE}PM专属提示：${NC}"
        echo "- 项目看板: docs/project-board.md"
        echo "- 周报模板: docs/team/pm-role.md"
        echo "- 决策记录: docs/DECISIONS.md"
        ;;
esac

echo ""
echo -e "${GREEN}🎯 现在可以开始工作了！${NC}"
