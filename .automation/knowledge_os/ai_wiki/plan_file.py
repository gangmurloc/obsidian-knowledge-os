"""Save a reviewed dry-run plan and apply exactly that plan later.

A scan with ``--write`` calls the model again, so its notes can differ from an earlier
dry-run. A saved plan holds the rendered notes of one dry-run; applying it makes no
LLM call and writes those notes byte for byte, after checking that nothing it depends
on has changed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..io_utils import atomic_write_json, atomic_write_text
from .engine import (
    AI_WIKI_RELATIVE_PATH,
    STATE_RELATIVE_PATH,
    ScanScope,
    _assert_ai_wiki_path,
    _load_state,
)
from .models import AIWikiError, ProcessingPlan
from .preprocess import AI_PROCESSING_VIEW_VERSION
from .render import load_existing_concept
from .source import load_source_note


PLAN_VERSION = 1
PLANS_RELATIVE_PATH = Path(".automation/state/plans")
WRITE_ACTIONS = {"create", "update"}


@dataclass(frozen=True)
class PlanChange:
    action: str
    title: str
    relative_path: str
    relation: str | None
    content: str


@dataclass(frozen=True)
class LoadedPlan:
    relative_path: str
    created_at: str
    model: str
    sources: tuple[str, ...]
    changes: tuple[PlanChange, ...]
    written: bool


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "digest"}
    return _sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def plan_block_reason(plan: ProcessingPlan) -> str | None:
    """Why this dry-run cannot be saved as an applicable plan, or None when it can."""
    if plan.failures:
        return "technical failure"
    if plan.quality_gate_status == "failed":
        return "semantic quality gate failure"
    if not plan.state_updates:
        return "no processed Source to record"
    return None


def save_plan(
    plan: ProcessingPlan,
    *,
    vault_root: Path,
    scope: ScanScope,
    provider_name: str,
    model_name: str,
    now: datetime | None = None,
) -> Path:
    reason = plan_block_reason(plan)
    if reason is not None:
        raise AIWikiError(f"plan was not saved because of {reason}")
    root = vault_root.resolve()
    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": {"mode": scope.mode, "source": scope.source},
        "provider": provider_name,
        "model": model_name,
        "processing_view_version": AI_PROCESSING_VIEW_VERSION,
        "quality_gate_status": plan.quality_gate_status,
        "sources": {
            relative: {
                "sha256": update["sha256"],
                "previous_state": plan.previous_state.get(relative),
            }
            for relative, update in plan.state_updates.items()
        },
        "changes": [
            {
                "action": change.action,
                "title": change.title,
                "path": _relative(change.path, root),
                "relation": change.relation,
                "content": change.content or "",
                "content_sha256": _sha256(change.content or ""),
                "base_sha256": change.base_sha256,
            }
            for change in plan.changed_notes
        ],
        "state_updates": copy.deepcopy(plan.state_updates),
    }
    payload["digest"] = _digest(payload)
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(scope.source or scope.mode).stem).strip("-")
    path = root / PLANS_RELATIVE_PATH / f"{created:%Y%m%dT%H%M%SZ}_{label or 'plan'}.json"
    atomic_write_json(path, payload, overwrite=False)
    atomic_write_text(review_path(path), _review_text(payload, path.name), overwrite=False)
    return path


def review_path(plan_path: Path) -> Path:
    """The human-readable copy written next to a plan; ``apply`` never reads it."""
    return plan_path.with_suffix(".review.md")


def _review_text(payload: dict[str, Any], plan_name: str) -> str:
    lines = [
        f"# AI-Wiki plan review: {plan_name}",
        "",
        "This file is a read-only copy for review. Applying the plan uses the JSON file,",
        "so edits made here have no effect.",
        "",
        f"- Created: {payload['created_at']}",
        f"- Model: {payload['provider']} / {payload['model']}",
        f"- Quality gate: {payload['quality_gate_status']}",
        "- Sources:",
        *(f"  - {relative}" for relative in payload["sources"]),
        "- Notes:",
        *(
            f"  - {change['action']}: {change['title']} ({change['path']})"
            for change in payload["changes"]
        ),
    ]
    for change in payload["changes"]:
        lines += [
            "",
            f"## {change['action']}: {change['title']}",
            "",
            f"Target: `{change['path']}`",
            "",
            "````markdown",
            change["content"].rstrip("\n"),
            "````",
        ]
    return "\n".join(lines) + "\n"


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AIWikiError(f"cannot read plan {path.name}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("plan_version") != PLAN_VERSION:
        raise AIWikiError(f"plan {path.name} has an unsupported format")
    if payload.get("digest") != _digest(payload):
        raise AIWikiError(
            f"plan {path.name} was modified after it was saved; run the scan again"
        )
    if not isinstance(payload.get("sources"), dict) or not isinstance(payload.get("changes"), list):
        raise AIWikiError(f"plan {path.name} is missing sources or changes")
    if not isinstance(payload.get("state_updates"), dict):
        raise AIWikiError(f"plan {path.name} is missing state updates")
    return payload


def apply_plan(*, vault_root: Path, plan_path: Path, write: bool = False) -> LoadedPlan:
    """Validate a saved plan against the vault and, with ``write``, apply it.

    Every check runs before the first write, so a stale or altered plan changes nothing.
    """
    root = vault_root.resolve()
    path = plan_path if plan_path.is_absolute() else root / plan_path
    payload = _read_payload(path)
    name = path.name
    if payload.get("processing_view_version") != AI_PROCESSING_VIEW_VERSION:
        raise AIWikiError(f"plan {name} was made with a different processing view version")
    if payload.get("quality_gate_status") == "failed":
        raise AIWikiError(f"plan {name} did not pass the quality gate")

    state_path = root / STATE_RELATIVE_PATH
    state = _load_state(state_path)
    for relative, recorded in payload["sources"].items():
        source = load_source_note(root / relative, root)
        if source.content_hash != recorded.get("sha256"):
            raise AIWikiError(f"Source changed since plan {name} was saved: {relative}")
        if state["sources"].get(relative) != recorded.get("previous_state"):
            raise AIWikiError(
                f"processing state changed since plan {name} was saved: {relative}"
            )
    if set(payload["state_updates"]) != set(payload["sources"]):
        raise AIWikiError(f"plan {name} has state updates for unknown Sources")

    output_root = (root / AI_WIKI_RELATIVE_PATH).resolve()
    changes: list[PlanChange] = []
    targets: set[Path] = set()
    for item in payload["changes"]:
        action = item.get("action")
        content = item.get("content")
        relative_path = item.get("path")
        if action not in WRITE_ACTIONS or not isinstance(content, str) or not content:
            raise AIWikiError(f"plan {name} contains an invalid change")
        if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
            raise AIWikiError(f"plan {name} contains an invalid target path")
        target = root / relative_path
        _assert_ai_wiki_path(target, output_root)
        if target.resolve() in targets:
            raise AIWikiError(f"plan {name} writes the same note twice: {relative_path}")
        targets.add(target.resolve())
        if _sha256(content) != item.get("content_sha256"):
            raise AIWikiError(f"plan {name} note content does not match its hash: {relative_path}")
        if action == "create":
            if target.exists():
                raise AIWikiError(f"note already exists and the plan would create it: {relative_path}")
        else:
            if not target.exists():
                raise AIWikiError(f"note to update no longer exists: {relative_path}")
            existing = load_existing_concept(target)
            if _sha256(existing.original_text) != item.get("base_sha256"):
                raise AIWikiError(f"note changed since plan {name} was saved: {relative_path}")
        changes.append(
            PlanChange(
                action=action,
                title=str(item.get("title", "")),
                relative_path=relative_path,
                relation=item.get("relation"),
                content=content,
            )
        )

    if write:
        for change in changes:
            atomic_write_text(
                root / change.relative_path,
                change.content,
                overwrite=change.action == "update",
            )
        next_state = copy.deepcopy(state)
        next_state["sources"].update(payload["state_updates"])
        atomic_write_json(state_path, next_state, overwrite=True)

    return LoadedPlan(
        relative_path=_relative(path, root),
        created_at=str(payload.get("created_at", "")),
        model=str(payload.get("model", "")),
        sources=tuple(payload["sources"]),
        changes=tuple(changes),
        written=write,
    )
