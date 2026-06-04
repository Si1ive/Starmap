#!/bin/bash
# StarMap 回滚脚本
# 使用方法: ./scripts/rollback.sh [版本号或commit]

TARGET=${1}

if [ -z "$TARGET" ]; then
    echo "❌ 请提供回滚目标"
    echo "用法:"
    echo "  ./scripts/rollback.sh v0.1.0    # 回滚到标签"
    echo "  ./scripts/rollback.sh abc1234   # 回滚到commit"
    echo "  ./scripts/rollback.sh HEAD~1    # 回滚到上一个版本"
    exit 1
fi

echo "⚠️  回滚到 $TARGET"
echo "=================="
echo ""
echo "⚠️  警告：此操作将丢弃当前工作区的更改！"
echo "是否继续？(yes/no)"
read -r answer

if [ "$answer" != "yes" ]; then
    echo "❌ 回滚取消"
    exit 1
fi

# 保存当前分支
current_branch=$(git branch --show-current)

# 创建回滚分支
echo "🌿 创建回滚分支..."
git checkout -b "rollback/$(date +%Y%m%d-%H%M%S)"

# 执行回滚
echo "⏪ 执行回滚..."
git reset --hard "$TARGET"

echo ""
echo "✅ 回滚完成！"
echo ""
echo "当前在分支: $(git branch --show-current)"
echo "回滚到: $(git log -1 --oneline)"
echo ""
echo "下一步:"
echo "1. 测试回滚后的代码"
echo "2. 如果正常，合并到main: git checkout main && git merge $(git branch --show-current)"
echo "3. 如果异常，回到原分支: git checkout $current_branch"
