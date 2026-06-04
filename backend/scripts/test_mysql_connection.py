"""
MySQL 连接测试脚本

验证 MySQL 连接、ORM 模型和 CRUD 操作。
"""

import os
import sys
import asyncio

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.mysql import mysql_client, get_mysql_client
from app.models.mysql_models import Person, Work, AdminUser
from app.core.config import settings


async def test_connection():
    """测试基础连接"""
    print("=" * 50)
    print("测试 1: MySQL 基础连接")
    print("=" * 50)
    
    client = await get_mysql_client()
    is_healthy = await client.health_check()
    
    if is_healthy:
        print("✓ MySQL 连接成功")
        print(f"  主机: {settings.MYSQL_HOST}:{settings.MYSQL_PORT}")
        print(f"  数据库: {settings.MYSQL_DATABASE}")
    else:
        print("✗ MySQL 连接失败")
        return False
    
    return True


async def test_crud():
    """测试 CRUD 操作"""
    print("\n" + "=" * 50)
    print("测试 2: CRUD 操作")
    print("=" * 50)
    
    client = await get_mysql_client()
    
    # 创建测试人物
    test_person = Person(
        id="person_test_001",
        name="测试艺人",
        name_en="Test Artist",
        gender="male",
        nationality="中国",
        summary="这是一个测试艺人",
        status="active",
        crawl_source="test"
    )
    
    created = await client.create(test_person)
    print(f"✓ 创建人物: {created.name} ({created.id})")
    
    # 查询
    found = await client.get_by_id(Person, "person_test_001")
    if found:
        print(f"✓ 查询人物: {found.name}")
    else:
        print("✗ 查询人物失败")
        return False
    
    # 更新
    updated = await client.update(Person, "person_test_001", {"name": "测试艺人（已更新）"})
    if updated:
        print(f"✓ 更新人物: {updated.name}")
    else:
        print("✗ 更新人物失败")
        return False
    
    # 统计
    count = await client.count(Person)
    print(f"✓ 统计人物: {count} 条记录")
    
    # 删除
    deleted = await client.delete(Person, "person_test_001")
    if deleted:
        print("✓ 删除人物成功")
    else:
        print("✗ 删除人物失败")
        return False
    
    return True


async def test_session():
    """测试会话管理"""
    print("\n" + "=" * 50)
    print("测试 3: 会话和事务")
    print("=" * 50)
    
    client = await get_mysql_client()
    
    # 测试会话上下文
    async with client.session() as session:
        from sqlalchemy import select, func
        result = await session.execute(select(func.count()).select_from(Person))
        count = result.scalar()
        print(f"✓ 会话查询: persons 表有 {count} 条记录")
    
    return True


async def test_admin_user():
    """测试默认管理员账号"""
    print("\n" + "=" * 50)
    print("测试 4: 默认管理员账号")
    print("=" * 50)
    
    client = await get_mysql_client()
    admin = await client.get_by_id(AdminUser, "admin_001")
    
    if admin:
        print(f"✓ 管理员账号存在")
        print(f"  用户名: {admin.username}")
        print(f"  邮箱: {admin.email}")
        print(f"  角色: {admin.role}")
        print(f"  状态: {'激活' if admin.is_active else '禁用'}")
    else:
        print("✗ 管理员账号不存在")
        return False
    
    return True


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("StarMap MySQL 连接测试")
    print("=" * 60)
    
    results = []
    
    try:
        results.append(("连接测试", await test_connection()))
        results.append(("CRUD测试", await test_crud()))
        results.append(("会话测试", await test_session()))
        results.append(("管理员测试", await test_admin_user()))
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if mysql_client._engine:
            await mysql_client.close()
    
    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status}: {name}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n🎉 所有测试通过！MySQL 集成成功。")
    else:
        print("\n⚠️ 部分测试失败，请检查配置。")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
