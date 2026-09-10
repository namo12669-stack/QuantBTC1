"""Small JSON state only. GitHub built-in token; no pickle, no PAT required."""
from __future__ import annotations
import base64
import json
import os
import re
from pathlib import Path
import requests
from .common import json_safe, read_json, write_json

class StateError(RuntimeError):
    pass

class Store:
    def __init__(self, local: Path, branch="btc-bot2-state"):
        self.local = local
        self.branch = branch
        self.repo = os.environ.get("GITHUB_REPOSITORY", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.remote = bool(self.repo and self.token)
        if self.remote and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo):
            raise StateError("Invalid repository name")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})

    def request(self, method, endpoint, payload=None, params=None):
        try:
            r = self.session.request(method, f"https://api.github.com/repos/{self.repo}/{endpoint}", json=payload, params=params, timeout=25)
        except requests.RequestException:
            raise StateError("GITHUB_STATE_NETWORK_ERROR") from None
        if r.status_code not in (200,201,404,422):
            raise StateError(f"GITHUB_STATE_HTTP_{r.status_code}; workflow needs contents: write for persistence")
        return r

    def get(self, name, default=None):
        self._validate(name)
        if not self.remote: return read_json(self.local / name, default)
        r = self.request("GET", f"contents/bot2/{name}", params={"ref": self.branch})
        if r.status_code == 404: return default
        if r.status_code != 200: raise StateError("Cannot read remote state")
        body = r.json()
        try:
            return json.loads(base64.b64decode(body["content"]).decode("utf-8"))
        except (ValueError, KeyError): raise StateError("Corrupt state JSON; not reset automatically") from None

    def put(self, name, data):
        self._validate(name)
        write_json(self.local / name, data)
        if not self.remote: return
        ref = self.request("GET", f"git/ref/heads/{self.branch}")
        if ref.status_code == 404:
            base_sha = self._base_sha_for_state_branch()
            created = self.request(
                "POST", "git/refs",
                {"ref": f"refs/heads/{self.branch}", "sha": base_sha},
            )
            if created.status_code not in (201, 422):
                raise StateError("Cannot create state branch")
            # 422 can mean another job created the branch between our GET and POST.
            verify = self.request("GET", f"git/ref/heads/{self.branch}")
            if verify.status_code != 200:
                raise StateError("State branch creation could not be verified")
        path = f"contents/bot2/{name}"
        old = self.request("GET", path, params={"ref": self.branch})
        content = json.dumps(json_safe(data), sort_keys=True, indent=2, allow_nan=False).encode()
        body = {"message": f"Bot2: update {name} [skip ci]", "content": base64.b64encode(content).decode(), "branch": self.branch}
        if old.status_code == 200:
            previous = old.json()
            if base64.b64decode(previous["content"]) == content: return
            body["sha"] = previous["sha"]
        r = self.request("PUT", path, body)
        if r.status_code not in (200,201): raise StateError("State update conflict; entry is not silently retried")


    def _base_sha_for_state_branch(self):
        """Resolve a safe commit SHA without assuming repository metadata has default_branch.

        GitHub Actions exposes GITHUB_SHA for both scheduled and workflow_dispatch runs.
        Prefer that immutable SHA.  Fall back to the current ref name, then the event
        payload's repository.default_branch.  If none can be resolved, fail explicitly
        rather than guessing a branch name.
        """
        sha = os.environ.get("GITHUB_SHA", "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            return sha

        ref_name = os.environ.get("GITHUB_REF_NAME", "").strip()
        if ref_name and ref_name != self.branch and re.fullmatch(r"[A-Za-z0-9._/-]+", ref_name):
            r = self.request("GET", f"git/ref/heads/{ref_name}")
            if r.status_code == 200:
                body = r.json()
                candidate = body.get("object", {}).get("sha", "")
                if re.fullmatch(r"[0-9a-fA-F]{40,64}", candidate):
                    return candidate

        event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
        if event_path:
            try:
                event = json.loads(Path(event_path).read_text(encoding="utf-8"))
                default_branch = event.get("repository", {}).get("default_branch", "")
            except (OSError, ValueError, TypeError):
                default_branch = ""
            if default_branch and re.fullmatch(r"[A-Za-z0-9._/-]+", default_branch):
                r = self.request("GET", f"git/ref/heads/{default_branch}")
                if r.status_code == 200:
                    body = r.json()
                    candidate = body.get("object", {}).get("sha", "")
                    if re.fullmatch(r"[0-9a-fA-F]{40,64}", candidate):
                        return candidate

        raise StateError(
            "STATE_BRANCH_BASE_SHA_UNAVAILABLE; GitHub Actions should provide GITHUB_SHA. "
            "Run from the repository default branch or inspect workflow environment."
        )

    @staticmethod
    def _validate(name):
        if name not in ("model.json", "runtime.json", "last_research.json"):
            raise StateError("Only whitelisted JSON state files may be written")
