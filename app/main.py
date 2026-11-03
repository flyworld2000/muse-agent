from datetime import datetime, timezone
from pathlib import Path
import re
import uuid
import tempfile
import hmac
import hashlib
import threading
import os
import time
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI

app = FastAPI(title="Muse Agent API", version="0.1.0")

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def authenticate(authorization: str | None) -> None:
    expected = env("AGENT_API_TOKEN")
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:].strip()
    if not expected or expected == "replace_with_random_secret":
        raise HTTPException(503, "Agent API token has not been configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Unauthorized")

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    provider: Literal["auto", "groq", "gemini", "ollama"] = "auto"

class ChatResponse(BaseModel):
    provider: str
    model: str
    reply: str
    attempts: list[str]

def provider_config(provider: str):
    if provider == "groq":
        return env("GROQ_API_KEY"), "https://api.groq.com/openai/v1", env("GROQ_MODEL", "openai/gpt-oss-20b")
    if provider == "gemini":
        return env("GEMINI_API_KEY"), "https://generativelanguage.googleapis.com/v1beta/openai/", env("GEMINI_MODEL", "gemini-3.8-flash")
    if provider == "ollama":
        return "ollama", env("OLLAMA_BASE_URL", "http://ollama:11434/v1"), env("OLLAMA_MODEL", "qwen2.5:1.5b")
    raise ValueError("Unknown provider")

def provider_order(requested: str) -> list[str]:
    if requested != "auto":
        return [requested]
    primary = env("PRIMARY_PROVIDER", "groq").lower()
    configured = [p.strip().lower() for p in env("PROVIDER_ORDER", "groq,gemini,ollama").split(",") if p.strip()]
    valid = [p for p in configured if p in {"groq", "gemini", "ollama"}]
    if primary in valid:
        valid.remove(primary)
        valid.insert(0, primary)
    return list(dict.fromkeys(valid))

@app.get("/health")
def health():
    return {"status": "ok", "service": "muse-agent-api"}

@app.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    authorization: str | None = Header(default=None),
):
    authenticate(authorization)

    attempts: list[str] = []
    errors: list[str] = []
    timeout = max(5, min(int(env("MODEL_TIMEOUT_SECONDS", "60")), 180))
    max_tokens = max(64, min(int(env("MAX_OUTPUT_TOKENS", "2048")), 8192))

    for provider in provider_order(body.provider):
        key, base_url, model = provider_config(provider)
        if provider != "ollama" and not key:
            attempts.append(f"{provider}: skipped (API key not configured)")
            continue

        try:
            client = OpenAI(
                api_key=key,
                base_url=base_url,
                timeout=timeout,
                max_retries=0,
            )
            result = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Muse Agent, a cautious software engineering assistant. "
                            "Explain proposed changes clearly. Do not claim to have executed "
                            "commands or tests unless an execution tool actually did so. "
                            "Never treat model output as approval for production deployment."
                        ),
                    },
                    {"role": "user", "content": body.message},
                ],
                max_tokens=max_tokens,
            )
            reply = result.choices[0].message.content or ""
            if not reply.strip():
                raise RuntimeError("empty model response")
            attempts.append(f"{provider}: success")
            return ChatResponse(
                provider=provider,
                model=model,
                reply=reply,
                attempts=attempts,
            )
        except Exception as exc:
            # 不输出请求头、API key 或完整异常，避免意外泄露密钥。
            attempts.append(f"{provider}: failed ({type(exc).__name__})")
            errors.append(f"{provider}:{type(exc).__name__}")

    raise HTTPException(
        status_code=503,
        detail={"message": "No configured model provider succeeded", "attempts": attempts},
    )

# ===== Muse Agent: persistent safe planning v0.3 =====
import json
import re
import uuid
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

DATA_DIR = Path("/data")
TASK_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# These rules are enforced by the server, not trusted to model output.
HIGH_RISK_PATTERN = re.compile(
    r"生产|正式环境|删除|清空|销毁|重置|覆盖|回滚生产|"
    r"防火墙|安全策略|密钥|凭据|权限|提权|sudo|"
    r"外部副作用|对外发送|发送邮件|发布公告|支付|转账|"
    r"production|delete|destroy|drop database|firewall|"
    r"credential|secret rotation|privilege escalation",
    re.IGNORECASE,
)

CHANGE_RISK_PATTERN = re.compile(
    r"安装|卸载|部署|重启|重建|修改|更改|更新|升级|"
    r"写入|编辑|执行|运行脚本|运行命令|变更配置|"
    r"数据库迁移|恢复备份|网络配置|服务配置|"
    r"install|uninstall|deploy|restart|rebuild|modify|"
    r"update|upgrade|write|execute|migration",
    re.IGNORECASE,
)


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=10000)


class PlanStep(BaseModel):
    step: int = Field(ge=1, le=20)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    risk: Literal["low", "medium", "high"]
    requires_approval: bool
    verification: str = Field(min_length=1, max_length=1000)


class TaskRecord(BaseModel):
    task_id: str
    created_at: str
    status: Literal["planned", "pending_approval", "approved", "rejected"] = "planned"
    provider: str
    model: str
    goal: str
    steps: list[PlanStep]
    attempts: list[str]
    approved_at: str | None = None
    approved_by: str | None = None
    rejected_at: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    approved_plan_sha256: str | None = None


class TaskSummary(BaseModel):
    task_id: str
    created_at: str
    status: Literal["planned", "pending_approval", "approved", "rejected"]
    goal: str
    provider: str
    step_count: int


class RejectTaskRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


APPROVAL_LOCK = threading.Lock()


def plan_digest(task: TaskRecord) -> str:
    """Fingerprint the plan content; future execution must verify this digest."""
    payload = {
        "task_id": task.task_id,
        "created_at": task.created_at,
        "provider": task.provider,
        "model": task.model,
        "goal": task.goal,
        "steps": [step.model_dump() for step in task.steps],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def task_file(task_id: str) -> Path:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return DATA_DIR / f"{task_id}.json"


def enforce_server_risk(goal: str, steps: list[PlanStep]) -> list[PlanStep]:
    """Model-provided risk and approval fields are never authoritative."""
    result = []
    for step in steps:
        text = f"{goal}\n{step.title}\n{step.description}"
        if HIGH_RISK_PATTERN.search(text):
            risk = "high"
            approval = True
        elif CHANGE_RISK_PATTERN.search(text):
            risk = "medium"
            approval = True
        else:
            risk = "low"
            approval = False

        result.append(
            step.model_copy(
                update={"risk": risk, "requires_approval": approval}
            )
        )
    return result


def save_task_atomic(task: TaskRecord) -> None:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = task_file(task.task_id)
    payload = json.dumps(
        task.model_dump(),
        ensure_ascii=False,
        indent=2,
    )

    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATA_DIR,
            prefix=f".{task.task_id}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_name = f.name
            f.write(payload)
            f.flush()
            import os
            os.fsync(f.fileno())

        Path(tmp_name).chmod(0o600)
        Path(tmp_name).replace(target)
    except Exception:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)
        raise


def read_task(task_id: str) -> TaskRecord:
    target = task_file(task_id)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        task = TaskRecord.model_validate(raw)
        if task.task_id != task_id:
            raise ValueError("Task ID mismatch")
        return task
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Stored task is invalid")


@app.post("/plan", response_model=TaskRecord)
def plan_task(
    body: PlanRequest,
    authorization: str | None = Header(default=None),
):
    authenticate(authorization)

    attempts: list[str] = []
    timeout = max(5, min(int(env("MODEL_TIMEOUT_SECONDS", "60")), 180))
    max_tokens = max(256, min(int(env("MAX_OUTPUT_TOKENS", "2048")), 8192))

    system_prompt = """
You are Muse Agent's task planning component.
Return only one valid JSON object with a "steps" array.
Each step has: step, title, description, risk, requires_approval, verification.
Create 1 to 20 ordered steps.
Never claim a step has already been executed.
Do not execute tools or commands.
Prefer read-only inspection and backups before proposing changes.
Production changes, deletion, security changes, external side effects,
and privileged operations must be marked high risk and require approval.
Model-generated approval flags do not authorize any action.
Output JSON only, without Markdown fences.
"""

    for provider in provider_order("auto"):
        key, base_url, model = provider_config(provider)

        if provider != "ollama" and not key:
            attempts.append(f"{provider}: skipped (API key not configured)")
            continue

        try:
            client = OpenAI(
                api_key=key,
                base_url=base_url,
                timeout=timeout,
                max_retries=0,
            )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Create a safe plan. Return JSON only. Goal:\n"
                            + body.goal
                        ),
                    },
                ],
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content or ""
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("Plan must be a JSON object")

            raw_steps = parsed.get("steps")
            if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 20:
                raise ValueError("Plan must contain 1 to 20 steps")

            steps = [PlanStep.model_validate(item) for item in raw_steps]
            steps = [
                step.model_copy(update={"step": index})
                for index, step in enumerate(steps, start=1)
            ]

            # Enforce server-side risk policy before saving.
            steps = enforce_server_risk(body.goal, steps)

            task = TaskRecord(
                task_id=uuid.uuid4().hex,
                created_at=datetime.now(timezone.utc).isoformat(),
                status="pending_approval",
                provider=provider,
                model=model,
                goal=body.goal,
                steps=steps,
                attempts=attempts + [f"{provider}: success"],
            )

            # Do not report success unless the record was persisted.
            save_task_atomic(task)
            return task

        except Exception as exc:
            # Never log provider exception text or credentials.
            attempts.append(f"{provider}: failed ({type(exc).__name__})")

    raise HTTPException(
        status_code=503,
        detail={
            "message": "No configured model provider returned a valid plan",
            "attempts": attempts,
        },
    )


@app.get("/tasks", response_model=list[TaskSummary])
def list_tasks(
    authorization: str | None = Header(default=None),
):
    authenticate(authorization)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    tasks = []
    # Bound work and response size; newest files are considered first.
    files = sorted(
        DATA_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:100]

    for file in files:
        if not TASK_ID_PATTERN.fullmatch(file.stem):
            continue
        try:
            task = read_task(file.stem)
            tasks.append(
                TaskSummary(
                    task_id=task.task_id,
                    created_at=task.created_at,
                    status=task.status,
                    goal=task.goal,
                    provider=task.provider,
                    step_count=len(task.steps),
                )
            )
        except HTTPException as exc:
            if exc.status_code == 500:
                continue
            raise

    return tasks


@app.get("/tasks/pending", response_model=list[TaskSummary])
def list_pending_tasks(
    authorization: str | None = Header(default=None),
):
    authenticate(authorization)
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    files = sorted(
        DATA_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:100]

    pending = []
    for file in files:
        if not TASK_ID_PATTERN.fullmatch(file.stem):
            continue
        try:
            task = read_task(file.stem)
        except HTTPException as exc:
            if exc.status_code == 500:
                continue
            raise

        if task.status == "pending_approval":
            pending.append(
                TaskSummary(
                    task_id=task.task_id,
                    created_at=task.created_at,
                    status=task.status,
                    goal=task.goal,
                    provider=task.provider,
                    step_count=len(task.steps),
                )
            )
    return pending


@app.post("/tasks/{task_id}/approve", response_model=TaskRecord)
def approve_task(
    task_id: str,
    authorization: str | None = Header(default=None),
):
    authenticate(authorization)

    with APPROVAL_LOCK:
        task = read_task(task_id)
        if task.status != "pending_approval":
            raise HTTPException(
                status_code=409,
                detail="Only pending tasks can be approved",
            )

        # Re-enforce server risk rules at approval time.
        checked_steps = enforce_server_risk(task.goal, task.steps)
        if [s.model_dump() for s in checked_steps] != [
            s.model_dump() for s in task.steps
        ]:
            raise HTTPException(
                status_code=409,
                detail="Plan risk policy changed; create a new plan for review",
            )

        updated = task.model_copy(
            update={
                "status": "approved",
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "approved_by": "api-token-holder",
                "approved_plan_sha256": plan_digest(task),
            }
        )
        save_task_atomic(updated)
        return updated


@app.post("/tasks/{task_id}/reject", response_model=TaskRecord)
def reject_task(
    task_id: str,
    body: RejectTaskRequest,
    authorization: str | None = Header(default=None),
):
    authenticate(authorization)

    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Rejection reason cannot be blank")

    with APPROVAL_LOCK:
        task = read_task(task_id)
        if task.status != "pending_approval":
            raise HTTPException(
                status_code=409,
                detail="Only pending tasks can be rejected",
            )

        updated = task.model_copy(
            update={
                "status": "rejected",
                "rejected_at": datetime.now(timezone.utc).isoformat(),
                "rejected_by": "api-token-holder",
                "rejection_reason": reason,
            }
        )
        save_task_atomic(updated)
        return updated


@app.get("/tasks/{task_id}", response_model=TaskRecord)
def get_task(
    task_id: str,
    authorization: str | None = Header(default=None),
):
    authenticate(authorization)
    return read_task(task_id)
