"""只读候选文件验证；不执行代码、不写入候选目录。"""

import hashlib
import json
import os
import stat
import re
from pathlib import Path

from policy import (
    MAX_FILE_SIZE,
    MAX_TOTAL_SIZE,
    validate_content_size,
    validate_proposal_paths,
)

MAX_MANIFEST_SIZE = 64 * 1024


def _read_regular_file(
    root_fd: int,
    relative_path: str,
    max_size: int,
) -> bytes:
    """逐级使用 dir_fd 和 O_NOFOLLOW，拒绝所有符号链接路径。"""
    parts = relative_path.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("候选文件路径无效")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )

    current_fd = os.dup(root_fd)
    file_fd = None

    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                directory_flags,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd

        file_fd = os.open(
            parts[-1],
            file_flags,
            dir_fd=current_fd,
        )

        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("候选输入不是普通文件")
        if info.st_size > max_size:
            raise ValueError("候选输入超过大小限制")

        chunks = []
        total = 0

        while True:
            chunk = os.read(file_fd, min(65536, max_size + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_size:
                raise ValueError("候选输入超过大小限制")

        return b"".join(chunks)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(current_fd)



def _validate_tree(
    directory_fd: int,
    prefix: str,
    expected_files: set[str],
) -> None:
    """拒绝未声明文件、额外目录、符号链接和特殊文件。"""
    expected_dirs = set()

    for path in expected_files:
        parts = path.split("/")
        for index in range(1, len(parts)):
            expected_dirs.add("/".join(parts[:index]))

    def walk(fd: int, relative_dir: str) -> None:
        for name in os.listdir(fd):
            relative = f"{relative_dir}/{name}" if relative_dir else name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)

            if stat.S_ISLNK(info.st_mode):
                raise ValueError("候选目录不允许符号链接")

            if stat.S_ISDIR(info.st_mode):
                if relative not in expected_dirs:
                    raise ValueError("候选目录包含未声明目录")

                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                )
                child_fd = os.open(name, flags, dir_fd=fd)
                try:
                    walk(child_fd, relative)
                finally:
                    os.close(child_fd)

            elif stat.S_ISREG(info.st_mode):
                if relative not in expected_files:
                    raise ValueError("候选目录包含未声明文件")
            else:
                raise ValueError("候选目录包含特殊文件")

    walk(directory_fd, prefix)


def candidate_digest(files: dict[str, bytes]) -> str:
    """对已验证的候选文件内容计算确定性 SHA-256 摘要。"""
    if not isinstance(files, dict) or not files:
        raise ValueError("候选文件集合不能为空")

    records = []
    for relative in sorted(files):
        if not isinstance(relative, str):
            raise ValueError("候选文件路径必须是字符串")
        content = files[relative]
        if not isinstance(content, bytes):
            raise ValueError("候选文件内容必须是字节数据")

        records.append({
            "path": relative,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })

    canonical = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(canonical).hexdigest()


def validate_candidate(
    candidates_root_fd: int,
    *,
    expected_task_id: str,
    expected_plan_sha256: str,
    expected_candidate_id: str,
) -> dict[str, bytes]:
    """从可信 candidates 根目录 fd 逐级打开并验证候选目录。"""

    id_pattern = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
    if not isinstance(expected_task_id, str) or not id_pattern.fullmatch(expected_task_id):
        raise ValueError("任务 ID 格式无效")
    if not isinstance(expected_candidate_id, str) or not id_pattern.fullmatch(expected_candidate_id):
        raise ValueError("候选 ID 格式无效")

    if (
        not isinstance(expected_plan_sha256, str)
        or len(expected_plan_sha256) != 64
        or any(c not in "0123456789abcdef" for c in expected_plan_sha256)
    ):
        raise ValueError("计划 SHA-256 格式无效")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )

    task_fd = None
    root_fd = None

    try:
        root_info = os.fstat(candidates_root_fd)
        if not stat.S_ISDIR(root_info.st_mode):
            raise ValueError("候选根目录文件描述符无效")

        task_fd = os.open(
            expected_task_id,
            directory_flags,
            dir_fd=candidates_root_fd,
        )
        root_fd = os.open(
            expected_candidate_id,
            directory_flags,
            dir_fd=task_fd,
        )

        root_entries = set(os.listdir(root_fd))
        if root_entries != {"manifest.json", "files"}:
            raise ValueError("候选根目录包含缺失或未授权的内容")

        raw_manifest = _read_regular_file(
            root_fd, "manifest.json", MAX_MANIFEST_SIZE
        )

        try:
            manifest = json.loads(raw_manifest.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("候选清单不是有效 UTF-8 JSON")

        if not isinstance(manifest, dict):
            raise ValueError("候选清单格式无效")

        required_manifest_keys = {
            "schema_version", "task_id", "approved_plan_sha256",
            "candidate_id", "files",
        }
        if set(manifest) != required_manifest_keys:
            raise ValueError("候选清单字段不符合规定")

        if manifest.get("schema_version") != 1:
            raise ValueError("不支持的候选清单版本")
        if manifest.get("task_id") != expected_task_id:
            raise ValueError("候选任务 ID 不匹配")
        if manifest.get("approved_plan_sha256") != expected_plan_sha256:
            raise ValueError("候选计划审批哈希不匹配")
        if manifest.get("candidate_id") != expected_candidate_id:
            raise ValueError("候选 ID 不匹配")

        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise ValueError("候选文件清单格式无效")

        paths = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("候选文件条目格式无效")
            if set(entry) != {"path", "size", "sha256"}:
                raise ValueError("候选文件条目字段不符合规定")
            paths.append(entry.get("path"))

        validated_paths = validate_proposal_paths(paths)

        files_fd = os.open(
            "files",
            directory_flags,
            dir_fd=root_fd,
        )
        try:
            _validate_tree(files_fd, "", set(validated_paths))
        finally:
            os.close(files_fd)

        total_size = 0
        result = {}

        for relative, entry in zip(validated_paths, entries):
            size = entry.get("size")
            expected_hash = entry.get("sha256")

            if type(size) is not int or size < 0:
                raise ValueError("候选文件大小字段无效")

            if (
                not isinstance(expected_hash, str)
                or len(expected_hash) != 64
                or any(c not in "0123456789abcdef" for c in expected_hash)
            ):
                raise ValueError("候选文件 SHA-256 格式无效")

            content = _read_regular_file(
                root_fd, f"files/{relative}", MAX_FILE_SIZE
            )
            validate_content_size(content)

            if len(content) != size:
                raise ValueError("候选文件大小与清单不匹配")

            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError("候选文件 SHA-256 不匹配")

            total_size += len(content)
            if total_size > MAX_TOTAL_SIZE:
                raise ValueError("候选文件总大小超过限制")

            result[relative] = content

        return result
    finally:
        if root_fd is not None:
            os.close(root_fd)
        if task_fd is not None:
            os.close(task_fd)
