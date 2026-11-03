"""Ed25519 审批票据验证；只验证，不签发、不修改票据。"""

import base64
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


MAX_TICKET_SIZE = 16 * 1024
MAX_TICKET_LIFETIME = timedelta(minutes=15)
CLOCK_SKEW = timedelta(seconds=30)

TICKET_FIELDS = {
    "schema_version",
    "ticket_id",
    "task_id",
    "approved_plan_sha256",
    "candidate_id",
    "candidate_sha256",
    "issued_at",
    "expires_at",
    "signature",
}

ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")



def _reject_duplicate_keys(pairs):
    """拒绝 JSON 对象中的重复字段，避免解析歧义。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 包含重复字段: {key}")
        result[key] = value
    return result


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} 必须使用 UTC ISO 8601 格式并以 Z 结尾")

    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} 时间格式无效") from exc

    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} 必须为 UTC 时间")

    return parsed


def _canonical_json(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_public_key(path: str | Path) -> Ed25519PublicKey:
    """加载 PEM 公钥，并严格要求 Ed25519 类型。"""
    key_data = Path(path).read_bytes()
    key = serialization.load_pem_public_key(key_data)

    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("审批公钥必须是 Ed25519 类型")

    return key


def verify_approval_ticket(
    ticket_data: bytes,
    public_key: Ed25519PublicKey,
    *,
    expected_task_id: str,
    expected_plan_sha256: str,
    expected_candidate_id: str,
    expected_candidate_sha256: str,
    now: datetime | None = None,
) -> dict:
    """验证票据签名、绑定关系、签发时间和有效期。"""

    if not isinstance(ticket_data, bytes):
        raise ValueError("票据必须是字节数据")

    if not ticket_data or len(ticket_data) > MAX_TICKET_SIZE:
        raise ValueError("票据为空或超过大小限制")

    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("验签公钥类型无效")

    try:
        ticket = json.loads(
            ticket_data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("票据 JSON 格式无效") from exc

    if not isinstance(ticket, dict) or set(ticket) != TICKET_FIELDS:
        raise ValueError("票据字段缺失或包含未授权字段")

    if type(ticket["schema_version"]) is not int or ticket["schema_version"] != 1:
        raise ValueError("不支持的票据版本")

    for field in ("task_id", "candidate_id"):
        if not isinstance(ticket[field], str) or not ID_PATTERN.fullmatch(ticket[field]):
            raise ValueError(f"{field} 格式无效")

    for field in ("approved_plan_sha256", "candidate_sha256"):
        if not isinstance(ticket[field], str) or not SHA256_PATTERN.fullmatch(ticket[field]):
            raise ValueError(f"{field} 格式无效")

    if not isinstance(ticket["ticket_id"], str):
        raise ValueError("ticket_id 格式无效")

    try:
        parsed_uuid = uuid.UUID(ticket["ticket_id"])
    except (ValueError, AttributeError) as exc:
        raise ValueError("ticket_id 必须是 UUID") from exc

    if str(parsed_uuid) != ticket["ticket_id"]:
        raise ValueError("ticket_id 必须使用标准 UUID 格式")

    if ticket["task_id"] != expected_task_id:
        raise ValueError("审批票据任务 ID 不匹配")

    if ticket["approved_plan_sha256"] != expected_plan_sha256:
        raise ValueError("审批票据计划摘要不匹配")

    if ticket["candidate_id"] != expected_candidate_id:
        raise ValueError("审批票据候选 ID 不匹配")

    if ticket["candidate_sha256"] != expected_candidate_sha256:
        raise ValueError("审批票据候选内容摘要不匹配")

    issued_at = _parse_timestamp(ticket["issued_at"], "issued_at")
    expires_at = _parse_timestamp(ticket["expires_at"], "expires_at")

    if expires_at <= issued_at:
        raise ValueError("票据过期时间必须晚于签发时间")

    if expires_at - issued_at > MAX_TICKET_LIFETIME:
        raise ValueError("票据有效期超过 15 分钟")

    current_time = now or datetime.now(timezone.utc)

    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("当前时间必须包含时区")

    current_time = current_time.astimezone(timezone.utc)

    if issued_at > current_time + CLOCK_SKEW:
        raise ValueError("票据签发时间超前")

    if current_time > expires_at + CLOCK_SKEW:
        raise ValueError("审批票据已过期")

    unsigned_ticket = {
        key: value
        for key, value in ticket.items()
        if key != "signature"
    }

    signature_text = ticket["signature"]
    if not isinstance(signature_text, str) or not signature_text:
        raise ValueError("票据签名缺失")

    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("票据签名 Base64 格式无效") from exc

    if len(signature) != 64:
        raise ValueError("Ed25519 签名长度无效")

    try:
        public_key.verify(signature, _canonical_json(unsigned_ticket))
    except InvalidSignature as exc:
        raise ValueError("审批票据签名验证失败") from exc

    return {
        "ticket_id": ticket["ticket_id"],
        "task_id": ticket["task_id"],
        "approved_plan_sha256": ticket["approved_plan_sha256"],
        "candidate_id": ticket["candidate_id"],
        "candidate_sha256": ticket["candidate_sha256"],
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
