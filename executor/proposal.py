"""生成受限代码变更提案；本模块不应用补丁、不执行代码。"""

import difflib
import hashlib
import json
import os
import re
import stat
import sys
import uuid

from datetime import datetime, timezone
from pathlib import Path

from candidate import candidate_digest
from policy import (
    MAX_PATCH_SIZE,
    MAX_TOTAL_SIZE,
    validate_content_size,
    validate_proposal_paths,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_authorized_file(root: Path, relative: str) -> bytes:
    """通过目录文件描述符逐级打开文件，拒绝符号链接和非普通文件。"""
    parts = relative.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("源码路径不安全")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)

    root_fd = os.open(root, directory_flags | nofollow)
    current_fd = root_fd
    opened_fds = []

    try:
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                directory_flags | nofollow,
                dir_fd=current_fd,
            )
            opened_fds.append(next_fd)
            current_fd = next_fd

        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
            dir_fd=current_fd,
        )

        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"源码不是普通文件：{relative}")

            chunks = []
            total = 0

            while True:
                chunk = os.read(file_fd, min(65536, 256 * 1024 + 1 - total))
                if not chunk:
                    break

                chunks.append(chunk)
                total += len(chunk)

                if total > 256 * 1024:
                    raise ValueError(f"源码文件超过大小限制：{relative}")

            content = b"".join(chunks)
            validate_content_size(content)
            return content
        finally:
            os.close(file_fd)

    except OSError as exc:
        raise ValueError(f"无法安全读取源码文件：{relative}") from exc
    finally:
        for fd in reversed(opened_fds):
            os.close(fd)
        os.close(root_fd)


def build_proposal(
    project_root: str | Path,
    proposal_root: str | Path,
    changes: dict[str, bytes],
    *,
    task_id: str,
    approved_plan_sha256: str,
    candidate_id: str,
    expected_candidate_sha256: str,
) -> dict:
    """
    生成受限代码变更提案。
    不修改 project_root 中的任何文件。
    提案目录及文件全程通过目录文件描述符操作。
    """
    # 提案必须绑定已审批任务、计划和具体候选。
    id_pattern = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
    hash_pattern = re.compile(r"^[0-9a-f]{64}$")

    if not isinstance(task_id, str) or not id_pattern.fullmatch(task_id):
        raise ValueError("任务 ID 无效")
    if not isinstance(candidate_id, str) or not id_pattern.fullmatch(candidate_id):
        raise ValueError("候选 ID 无效")
    if (
        not isinstance(approved_plan_sha256, str)
        or not hash_pattern.fullmatch(approved_plan_sha256)
    ):
        raise ValueError("已批准计划 SHA-256 无效")
    if (
        not isinstance(expected_candidate_sha256, str)
        or not hash_pattern.fullmatch(expected_candidate_sha256)
    ):
        raise ValueError("预期候选 SHA-256 无效")

    actual_candidate_sha256 = candidate_digest(changes)
    if actual_candidate_sha256 != expected_candidate_sha256:
        raise ValueError("候选摘要与审批票据不匹配")

    paths = validate_proposal_paths(list(changes))

    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("项目根目录无效")

    originals = {}
    proposed = {}
    total_size = 0
    diff_lines = []

    for relative in paths:
        new_content = changes[relative]
        if not isinstance(new_content, bytes):
            raise ValueError("新文件内容必须是字节数据")
        validate_content_size(new_content)

        old_content = _read_authorized_file(root, relative)

        try:
            old_text = old_content.decode("utf-8")
            new_text = new_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"只支持 UTF-8 文本文件：{relative}") from exc

        total_size += len(old_content) + len(new_content)
        if total_size > MAX_TOTAL_SIZE:
            raise ValueError("提案总文件大小超过限制")

        originals[relative] = old_content
        proposed[relative] = new_content

        diff_lines.extend(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )

    patch = "".join(diff_lines).encode("utf-8")

    if not patch:
        raise ValueError("提案没有实际代码变更")

    if len(patch) > MAX_PATCH_SIZE:
        raise ValueError("补丁大小超过限制")

    proposal_id = uuid.uuid4().hex

    manifest = {
        "proposal_id": proposal_id,
        "task_id": task_id,
        "approved_plan_sha256": approved_plan_sha256,
        "candidate_id": candidate_id,
        "candidate_sha256": actual_candidate_sha256,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            relative: {
                "original_sha256": sha256(originals[relative]),
                "proposed_sha256": sha256(proposed[relative]),
                "original_size": len(originals[relative]),
                "proposed_size": len(proposed[relative]),
            }
            for relative in paths
        },
        "patch_sha256": sha256(patch),
        "patch_size": len(patch),
        "status": "proposed",
    }

    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
    ).encode("utf-8")

    proposal_base = Path(os.path.abspath(proposal_root))
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open("/", directory_flags)
    proposal_fd = None
    created_files = []
    directory_created = False

    try:
        # 从文件系统根目录逐级打开；任何一级符号链接都会被拒绝。
        for part in proposal_base.parts[1:]:
            if part in ("", ".", ".."):
                raise ValueError("提案目录路径不安全")

            try:
                next_fd = os.open(
                    part,
                    directory_flags | nofollow,
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
                next_fd = os.open(
                    part,
                    directory_flags | nofollow,
                    dir_fd=current_fd,
                )

            os.close(current_fd)
            current_fd = next_fd

        # current_fd 此时就是经过逐级 O_NOFOLLOW 验证的提案根目录。
        os.mkdir(proposal_id, mode=0o700, dir_fd=current_fd)
        directory_created = True

        proposal_fd = os.open(
            proposal_id,
            directory_flags | nofollow,
            dir_fd=current_fd,
        )
        os.fchmod(proposal_fd, 0o750)

        # 排他创建文件，拒绝覆盖及符号链接。
        for filename, content in (
            ("patch.diff", patch),
            ("manifest.json", manifest_bytes),
        ):
            fd = os.open(
                filename,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o640,
                dir_fd=proposal_fd,
            )
            created_files.append(filename)

            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())

        os.fsync(proposal_fd)
        os.fsync(current_fd)

    except OSError as exc:
        raise ValueError(
            "提案目录无法安全创建或写入"
        ) from exc

    finally:
        failed = sys.exc_info()[0] is not None

        if failed and proposal_fd is not None:
            for filename in reversed(created_files):
                try:
                    os.unlink(filename, dir_fd=proposal_fd)
                except OSError:
                    pass

        if proposal_fd is not None:
            try:
                os.close(proposal_fd)
            except OSError:
                pass

        if failed and directory_created:
            try:
                os.rmdir(proposal_id, dir_fd=current_fd)
            except OSError:
                pass

        try:
            os.close(current_fd)
        except OSError:
            pass

    return manifest
