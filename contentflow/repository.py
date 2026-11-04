"""SQLite 持久化审核快照与单任务提交锁。"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sqlite3
import uuid

from contentflow.domain import Content, FlowError, fingerprint

ACTIVE = ("submitting", "processing", "uncertain")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, topic TEXT NOT NULL, content TEXT NOT NULL,
                    source TEXT NOT NULL, reviewed_hash TEXT, usage TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, draft_id TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL UNIQUE, snapshot TEXT NOT NULL,
                    task_id TEXT, state TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '', file_path TEXT, metadata TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs((1))
                    WHERE state IN ('submitting','processing','uncertain');
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def new_draft(self, topic: str, content: Content, usage: dict | None = None, source: str = "pixabay") -> str:
        fingerprint(topic, content, source)
        identity = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?)", (identity, topic, json.dumps(content.as_dict(), ensure_ascii=False), source, None, json.dumps(usage or {}), now(), now()))
        return identity

    def drafts(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM drafts ORDER BY created_at DESC")]

    def draft(self, identity: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM drafts WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise FlowError("draft", "找不到这条草稿，请重新选择。")
        return dict(row)

    def confirm(self, identity: str, topic: str, content: Content, source: str) -> str:
        digest = fingerprint(topic, content, source)
        with self.connect() as db:
            cursor = db.execute("UPDATE drafts SET topic=?,content=?,source=?,reviewed_hash=?,updated_at=? WHERE id=?", (topic, json.dumps(content.as_dict(), ensure_ascii=False), source, digest, now(), identity))
            if cursor.rowcount != 1:
                raise FlowError("draft", "找不到待审核草稿。")
        return digest

    def reserve(self, identity: str, expected_hash: str) -> dict:
        """先持久化 submitting，再向后端发唯一一次 POST。"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM drafts WHERE id=?", (identity,)).fetchone()
            if row is None or not row["reviewed_hash"] or row["reviewed_hash"] != expected_hash:
                raise FlowError("approval", "内容已改变或尚未审核，请重新确认。")
            content = Content.parse(json.loads(row["content"]))
            if fingerprint(row["topic"], content, row["source"]) != expected_hash:
                raise FlowError("approval", "审核快照不一致，已禁止提交。")
            # 新建草稿是用户明确的新尝试；同一草稿的同一审核版本只能提交一次。
            submission_hash = hashlib.sha256((identity + ":" + expected_hash).encode()).hexdigest()
            if db.execute("SELECT 1 FROM jobs WHERE snapshot_hash=?", (submission_hash,)).fetchone():
                raise FlowError("duplicate", "这份审核内容已提交，请查看已有任务；重试需建立新的草稿。")
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('submitting','processing','uncertain')").fetchone():
                raise FlowError("busy", "已有正在执行或需要核对的任务，请先处理它。")
            identity_job = str(uuid.uuid4())
            snapshot = {"topic": row["topic"], "content": content.as_dict(), "source": row["source"], "reviewed_content_hash": expected_hash}
            db.execute("INSERT INTO jobs(id,draft_id,snapshot_hash,snapshot,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (identity_job, identity, submission_hash, json.dumps(snapshot, ensure_ascii=False), "submitting", now(), now()))
        return self.job(identity_job)

    def job(self, identity: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise FlowError("job", "找不到任务记录。")
        return dict(row)

    def jobs(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY created_at DESC")]

    def update(self, identity: str, **fields) -> dict:
        allowed = {"task_id", "state", "progress", "error", "file_path", "metadata"}
        if not fields or set(fields) - allowed:
            raise ValueError("Invalid job update")
        if "metadata" in fields:
            fields["metadata"] = json.dumps(fields["metadata"], ensure_ascii=False)
        fields["updated_at"] = now()
        with self.connect() as db:
            db.execute("UPDATE jobs SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?", (*fields.values(), identity))
        return self.job(identity)
