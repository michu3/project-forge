"""
github_cli_wrapper.py - GitHub CLI (gh) のラッパーモジュール

AIAgent（ロール）が直接 GitHub 操作（PRコメント、ラベル管理等）を
提案・実行できるようにするための基盤クラス。
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Dict

class GitHubCLIWrapper:
    def __init__(self, token: str, repo: str, cwd: Optional[Path] = None):
        """
        Args:
            token: GitHub Personal Access Token (GH_TOKEN)
            repo: 対象リポジトリ (owner/repo)
            cwd: コマンド実行時のカレントディレクトリ
        """
        self.token = token
        self.repo = repo
        self.cwd = cwd

    def _run(self, cmd: List[str]) -> subprocess.CompletedProcess:
        """共通の gh コマンド実行ロジック"""
        env = os.environ.copy()
        env["GH_TOKEN"] = self.token
        
        # リポジトリを明示的に指定（コマンドに含まれていない場合）
        if "--repo" not in cmd and cmd[1] in ["pr", "issue", "release", "repo", "api"]:
            # 特定のサブコマンドには --repo が必要
             if cmd[1] != "api": # api はパスに repo が含まれることが多い
                cmd.extend(["--repo", self.repo])

        return subprocess.run(
            cmd,
            cwd=str(self.cwd) if self.cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )

    def pr_comment(self, pr_number: str, body: str) -> bool:
        """PR にコメントを投稿する"""
        result = self._run(["gh", "pr", "comment", pr_number, "--body", body])
        return result.returncode == 0

    def pr_list(self, state: str = "open") -> List[Dict]:
        """PR の一覧を JSON 形式で取得する"""
        result = self._run(["gh", "pr", "list", "--state", state, "--json", "number,title,author,url"])
        if result.returncode == 0:
            return json.loads(result.stdout)
        return []

    def pr_view(self, pr_number: str) -> Dict:
        """特定の PR の詳細（Diff等）を取得する"""
        result = self._run(["gh", "pr", "view", pr_number, "--json", "number,title,body,state,url,files"])
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {}

    def issue_create(self, title: str, body: str, labels: List[str] = []) -> Optional[str]:
        """Issue を作成し、その URL を返す"""
        cmd = ["gh", "issue", "create", "--title", title, "--body", body]
        for label in labels:
            cmd.extend(["--label", label])
        
        result = self._run(cmd)
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def api_get(self, endpoint: str) -> Dict:
        """GitHub API (GET) を直接叩く"""
        result = self._run(["gh", "api", endpoint])
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {}
