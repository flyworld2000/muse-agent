"""代码变更执行器的服务端安全策略。"""

from pathlib import PurePosixPath

ALLOWED_FILES = frozenset({
    "app/learning_db.py",
    "app/migrate_v4.py",
    "tests/conftest.py",
    "tests/test_v4_catalog.py",
})

MAX_FILES_PER_PROPOSAL = 4
MAX_FILE_SIZE = 256 * 1024
MAX_TOTAL_SIZE = 512 * 1024
MAX_PATCH_SIZE = 128 * 1024


def validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("文件路径不能为空")

    if "\\" in value or "\x00" in value:
        raise ValueError("文件路径包含非法字符")

    path = PurePosixPath(value)

    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("不允许绝对路径或路径穿越")

    normalized = path.as_posix()

    if normalized != value:
        raise ValueError("文件路径不是规范格式")

    if normalized not in ALLOWED_FILES:
        raise ValueError("文件不在授权修改清单中")

    return normalized


def validate_proposal_paths(paths: list[str]) -> list[str]:
    if not isinstance(paths, list) or not paths:
        raise ValueError("变更文件清单不能为空")

    if len(paths) > MAX_FILES_PER_PROPOSAL:
        raise ValueError("变更文件数量超过限制")

    validated = [validate_relative_path(path) for path in paths]

    if len(set(validated)) != len(validated):
        raise ValueError("变更文件清单存在重复路径")

    return validated


def validate_content_size(content: bytes) -> None:
    if not isinstance(content, bytes):
        raise ValueError("文件内容必须是字节数据")

    if len(content) > MAX_FILE_SIZE:
        raise ValueError("单个文件超过大小限制")
