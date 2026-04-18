"""Dispatch the ingest workflow from an internal admin endpoint.

Wire this from FastAPI's `POST /admin/ingest/run` handler. Requires a GitHub token
with `actions:write` on the repo (provided via `GITHUB_TOKEN` env var).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class DispatchResult:
    ok: bool
    status_code: int
    detail: str


def dispatch_ingest(
    *,
    repo: str,
    workflow_file: str = "ingest.yml",
    ref: str = "main",
    force: bool = False,
    token: Optional[str] = None,
) -> DispatchResult:
    """POST to /repos/{repo}/actions/workflows/{workflow_file}/dispatches."""
    import httpx  # type: ignore

    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        return DispatchResult(False, 0, "GITHUB_TOKEN not set")

    url = (
        f"https://api.github.com/repos/{repo}"
        f"/actions/workflows/{workflow_file}/dispatches"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": ref, "inputs": {"force": "true" if force else "false"}}

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, json=payload)

    if resp.status_code == 204:
        return DispatchResult(True, 204, "dispatched")
    return DispatchResult(False, resp.status_code, resp.text)
