#!/bin/bash
# StarMap 发布脚本
# 使用方法: ./scripts/release.sh [版本号]

VERSION=${1}

if [ -z "$VERSION" ]; then
    echo "❌ 请提供版本号"
    echo "用法: ./scripts/release.sh v0.1.0"
    exit 1
fi

echo "🚀 发布 $VERSION"
echo "==============="

# 检查分支
current_branch=$(git branch --show-current)
if [ "$current_branch" != "develop" ]; then
    echo "⚠️  当前不在develop分支，是否切换？(y/n)"
    read -r answer
    if [ "$answer" = "y" ]; then
        git checkout develop
    else
        echo "❌ 发布取消"
        exit 1
    fi
fi

# 检查工作区是否干净
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  工作区有未提交的更改，请先提交"
    git status
    exit 1
fi

# 拉取最新代码
echo "📥 拉取最新代码..."
git pull origin develop

# 创建发布分支
echo "🌿 创建发布分支..."
git checkout -b "release/$VERSION"

# 更新版本号
echo "$VERSION" > VERSION
git add VERSION
git commit -m "chore(release): prepare $VERSION"

# 合并到main
echo "🔀 合并到main分支..."
git checkout main
git merge --no-ff "release/$VERSION" -m "release: $VERSION"

# 打标签
echo "🏷️  打标签..."
git tag -a "$VERSION" -m "Release $VERSION"

# 合并回develop
echo "🔀 合并回develop分支..."
git checkout develop
git merge --no-ff main -m "merge: $VERSION into develop"

# 删除发布分支
echo "🗑️  删除发布分支..."
git branch -d "release/$VERSION"

echo ""
echo "✅ 发布完成！"
echo ""
echo "下一步:"
echo "git push origin main"
echo "git push origin develop"
echo "git push origin $VERSION"
