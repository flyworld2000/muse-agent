#!/usr/bin/env python3
"""固定操作入口：仅允许在隔离工作区运行项目测试。"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

WORK = Path("/tmp/muse-work")
TEST_BASE = Path("/tmp/pytest-base")
SEED_DB = Path("/seed/learning.sqlite3")

# 只允许这四个源码/测试文件进入工作区
ALLOWED_INPUTS = {
    "app/learning_db.py": Path("/input/learning_db.py"),
    "app/migrate_v4.py": Path("/input/migrate_v4.py"),
    "tests/conftest.py": Path("/input/conftest.py"),
    "tests/test_v4_catalog.py": Path("/input/test_v4_catalog.py"),
}


def prepare_workspace():
    if not SEED_DB.is_file():
        raise RuntimeError("只读测试种子数据库不存在")

    # 只清理本执行器专用的临时目录
    for path in (WORK, TEST_BASE):
        if path.exists():
            shutil.rmtree(path)

    (WORK / "app").mkdir(parents=True)
    (WORK / "tests").mkdir(parents=True)
    TEST_BASE.mkdir(parents=True)

    for relative, source in ALLOWED_INPUTS.items():
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"授权输入文件缺失或不是普通文件：{source}")

        destination = WORK / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    (WORK / "app" / "__init__.py").touch()


def run_tests():
    prepare_workspace()

    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(WORK),
        "MUSE_TEST_SEED_DB": str(SEED_DB),
        "LEARNING_DB_PATH": str(WORK / "learning.sqlite3"),
    }

    command = [
        sys.executable,
        "-m", "pytest",
        "-q",
        f"--basetemp={TEST_BASE}",
    ]

    print("执行固定测试操作：pytest", flush=True)
    print("工作区：", WORK, flush=True)
    print("测试临时目录：", TEST_BASE, flush=True)

    result = subprocess.run(
        command,
        cwd=WORK,
        env=env,
        timeout=180,
        check=False,
    )
    return result.returncode


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "test":
        print("用法：python /executor/run.py test", file=sys.stderr)
        return 2

    try:
        return run_tests()
    except subprocess.TimeoutExpired:
        print("测试超时：超过 180 秒", file=sys.stderr)
        return 124
    except Exception as exc:
        print(f"执行器错误：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
