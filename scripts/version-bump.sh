#!/bin/bash
# StarMap 版本升级脚本
# 使用方法: ./scripts/version-bump.sh [patch|minor|major]

VERSION_TYPE=${1:-patch}

# 读取当前版本
if [ -f "VERSION" ]; then
    CURRENT_VERSION=$(cat VERSION)
else
    CURRENT_VERSION="0.0.0"
fi

# 解析版本号
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# 升级版本号
case $VERSION_TYPE in
    patch)
        PATCH=$((PATCH + 1))
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
    *)
        echo "❌ 无效的版本类型: $VERSION_TYPE"
        echo "用法: ./scripts/version-bump.sh [patch|minor|major]"
        exit 1
        ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"

# 更新版本文件
echo "$NEW_VERSION" > VERSION

# 更新package.json（如果存在）
if [ -f "frontend/package.json" ]; then
    sed -i '' "s/\"version\": \".*\"/\"version\": \"$NEW_VERSION\"/" frontend/package.json
fi

# 更新pyproject.toml（如果存在）
if [ -f "backend/pyproject.toml" ]; then
    sed -i '' "s/version = \".*\"/version = \"$NEW_VERSION\"/" backend/pyproject.toml
fi

# Git提交
git add VERSION frontend/package.json backend/pyproject.toml 2>/dev/null
git commit -m "chore(release): bump version to v$NEW_VERSION"
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"

echo "✅ 版本已升级到 v$NEW_VERSION"
echo ""
echo "下一步:"
echo "git push origin develop"
echo "git push origin v$NEW_VERSION"
