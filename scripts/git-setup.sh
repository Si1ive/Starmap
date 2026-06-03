#!/bin/bash
# StarMap Git 初始化脚本
# 使用方法: ./scripts/git-setup.sh

echo "🚀 StarMap Git 初始化"
echo "====================="

# 检查Git是否安装
if ! command -v git &> /dev/null; then
    echo "❌ Git未安装，请先安装Git"
    exit 1
fi

# 检查是否在Git仓库中
if [ ! -d .git ]; then
    echo "📦 初始化Git仓库..."
    git init
fi

# 配置Git用户信息（如果未配置）
if [ -z "$(git config user.email)" ]; then
    echo "⚠️  Git用户邮箱未配置"
    read -p "请输入你的Git邮箱: " email
    git config user.email "$email"
fi

if [ -z "$(git config user.name)" ]; then
    echo "⚠️  Git用户名未配置"
    read -p "请输入你的Git用户名: " name
    git config user.name "$name"
fi

# 创建分支
echo "🌿 创建分支..."
git checkout -b main 2>/dev/null || git checkout main
git checkout -b develop 2>/dev/null || git checkout develop

# 创建功能分支模板
echo "📝 创建功能分支模板..."
for branch in feature/backend-api feature/frontend-search feature/data-crawler; do
    git branch "$branch" 2>/dev/null || echo "分支 $branch 已存在"
done

echo ""
echo "✅ Git初始化完成！"
echo ""
echo "当前分支: $(git branch --show-current)"
echo ""
echo "所有分支:"
git branch -a
echo ""
echo "下一步:"
echo "1. 创建GitHub仓库: https://github.com/new"
echo "2. 运行: git remote add origin https://github.com/Si1ive/starmap.git"
echo "3. 运行: git push -u origin main"
echo "4. 运行: git push -u origin develop"
