"""
cicd_manager.py - GitHub CI/CD 連携モジュール

Project Forge が生成した成果物を新規 GitHub リポジトリへ Push し、
Pull Request を自動作成するモジュール。

依存ライブラリ:
    pip install PyGithub gitpython python-dotenv

環境変数:
    GITHUB_TOKEN: GitHub Personal Access Token (repo スコープ必要)
    GITHUB_USER:  GitHub ユーザー名 (例: "michu3")
"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .gemini_client import GeminiClient


# ========================
# データクラス
# ========================

class PRSpec:
    """Pull Request の仕様を保持するデータクラス"""

    def __init__(
        self,
        title: str,
        body: str,
        source_branch: str,
        target_branch: str = "main",
        labels: list = None,
        draft: bool = True,
    ):
        self.title = title
        self.body = body
        self.source_branch = source_branch
        self.target_branch = target_branch
        self.labels = labels or ["ai-generated", "needs-review"]
        self.draft = draft


class CICDResult:
    """CI/CD 実行結果"""

    def __init__(self, success: bool, pr_url: str = None, repo_url: str = None, branch: str = None, error: str = None):
        self.success = success
        self.pr_url = pr_url
        self.repo_url = repo_url
        self.branch = branch
        self.error = error

    def __repr__(self):
        if self.success:
            return f"CICDResult(✅ PR作成成功: {self.pr_url})"
        return f"CICDResult(❌ 失敗: {self.error})"


# ========================
# メインクラス
# ========================

class CICDManager:
    """
    GitHub へのリポジトリ新規作成、コードの Push、Pull Request 自動作成を担当するマネージャー。
    """

    def __init__(
        self,
        github_user: str,
        token: str,
        gemini_client: GeminiClient,
        base_branch: str = "main",
    ):
        """
        Args:
            github_user: リポジトリを作成するユーザー名
            token: GitHub Personal Access Token (repo スコープが必要)
            gemini_client: リポジトリ名生成に使用する Gemini クライアント
            base_branch: PR のマージ先ブランチ（デフォルト: "main"）
        """
        self.github_user = github_user
        self.token = token
        self.gemini = gemini_client
        self.base_branch = base_branch
        self.local_repo_path = None # create_pr_from_project 実行時にセットされる

    # ------------------------------------------
    # 公開メソッド
    # ------------------------------------------

    def create_pr_from_project(
        self,
        project_dir: Path,
        brief: str,
        phase_results: list,
    ) -> CICDResult:
        """
        Project Forge の実行結果から新規 GitHub リポジトリを作成し、PR を作成する。
        """
        self.local_repo_path = Path(project_dir)
        
        try:
            print(f"\n🚀 [CI/CD] Phase 6: Deliver (GitHub連携) 開始")
            
            # 1. リポジトリ名の自動生成
            repo_name = self._generate_repo_name(brief)
            full_repo_name = f"{self.github_user}/{repo_name}"
            print(f"📦 [CI/CD] リポジトリ構成: {full_repo_name}")

            # 2. リモートリポジトリの作成
            repo_url = self._create_remote_repo(repo_name, brief)
            print(f"☁️  [CI/CD] リモートリポジトリ作成完了: {repo_url}")

            # 3. ローカル Git の初期化と Initial Commit (main作成用)
            self._init_local_repo(full_repo_name)
            
            # 4. ブランチ名の生成と作業ブランチの作成
            branch_name = self._generate_branch_name(brief)
            self._git_create_branch(branch_name)
            print(f"🔀 [CI/CD] 作業ブランチ作成: {branch_name}")

            # 5. プロジェクトの全成果物を Add, Commit & Push
            commit_msg = f"[Forge] {brief[:60]} - 自動実装完了"
            self._git_commit_and_push(branch_name, ".", commit_msg)
            print(f"⬆️  [CI/CD] コードの Push 完了")

            # 6. PR 本文を生成
            pr_body = self._build_pr_body(brief, phase_results)

            # 7. PR を作成
            pr_spec = PRSpec(
                title=f"[🤖 Forge] {brief[:60]}",
                body=pr_body,
                source_branch=branch_name,
                target_branch=self.base_branch,
            )
            pr_url = self._create_github_pr(full_repo_name, pr_spec)
            print(f"✅ [CI/CD] PR 作成完了: {pr_url}")

            return CICDResult(success=True, pr_url=pr_url, repo_url=repo_url, branch=branch_name)

        except Exception as e:
            error_msg = f"CI/CD 処理失敗: {str(e)}"
            print(f"❌ [CI/CD] {error_msg}")
            return CICDResult(success=False, error=error_msg)

    # ------------------------------------------
    # Gemini による自動生成
    # ------------------------------------------

    def _generate_repo_name(self, brief: str) -> str:
        """案件概要から適切な GitHub リポジトリ名を生成する"""
        prompt = f"""
以下の案件概要に基づいて、適切な GitHub リポジトリ名を1つ生成してください。
条件:
- 英語の小文字、数字、ハイフン(-)のみを使用すること。
- 端的で内容が伝わる短い名前にすること（最大3〜4単語程度）。
- スペースや特殊文字は一切含めないこと。
- 余計な説明は省き、リポジトリ名のみを出力すること。

案件概要:
{brief}
"""
        try:
            response = self.gemini.generate(prompt).strip()
            # フォーマットの強制
            slug = re.sub(r"[^\w\s-]", "", response)
            slug = re.sub(r"[\s_]+", "-", slug).lower()
            if not slug:
                slug = "forge-generated-project"
            return slug
        except Exception as e:
            print(f"⚠️ リポジトリ名生成に失敗しました。デフォルト名を使用します。({e})")
            date_str = datetime.now().strftime("%Y%m%d%H%M")
            return f"forge-project-{date_str}"

    # ------------------------------------------
    # GitHub API 操作
    # ------------------------------------------

    def _create_remote_repo(self, repo_name: str, brief: str) -> str:
        """リモートリポジトリを新規作成する"""
        try:
            # PyGithub を使った実装（推奨）
            from github import Github
            g = Github(self.token)
            user = g.get_user()
            
            # 既存確認
            try:
                repo = user.get_repo(repo_name)
                print(f"⚠️ リポジトリ {repo_name} は既に存在します。そのまま使用します。")
                return repo.html_url
            except:
                pass # 存在しない場合は新規作成

            repo = user.create_repo(
                name=repo_name,
                description=f"Generated by Project Forge: {brief[:100]}",
                private=True,
                auto_init=False,
            )
            return repo.html_url
        except ImportError:
            # gh CLI フォールバック
            description_safe = brief[:100].replace("\n", " ").replace("\r", " ").strip()
            # 引数リスト形式で渡すことでスペースも安全に扱う
            cmd = [
                "gh", "repo", "create", f"{self.github_user}/{repo_name}",
                "--private", "--description", f"Generated by Project Forge: {description_safe}"
            ]
            
            result = self._run_gh_cmd(cmd)
            if "already exists" not in result.stderr and result.returncode != 0:
                raise RuntimeError(f"gh CLI によるリポジトリ作成失敗:\n{result.stderr}")
            
            return f"https://github.com/{self.github_user}/{repo_name}"


    def _create_github_pr(self, full_repo_name: str, pr_spec: PRSpec) -> str:
        """GitHub REST API を使って Pull Request を作成する"""
        print(f"DEBUG: creating GH PR for {full_repo_name}")
        try:
            # PyGithub を使った実装
            from github import Github
            g = Github(self.token)
            repo = g.get_repo(full_repo_name)

            pr = repo.create_pull(
                title=pr_spec.title,
                body=pr_spec.body,
                head=pr_spec.source_branch,
                base=pr_spec.target_branch,
                draft=pr_spec.draft,
            )

            # ラベル付与
            for label_name in pr_spec.labels:
                try:
                    label = repo.get_label(label_name)
                except:
                    label = repo.create_label(label_name, color="0075ca")
                pr.add_to_labels(label)

            return pr.html_url

        except ImportError:
            # gh CLI フォールバック
            print(f"DEBUG: Using gh CLI to create PR")
            cmd = [
                "gh", "pr", "create",
                "--title", pr_spec.title,
                "--body", pr_spec.body,
                "--base", pr_spec.target_branch,
                "--head", pr_spec.source_branch,
                "--repo", full_repo_name,
            ]
            if pr_spec.draft:
                cmd.append("--draft")

            result = self._run_gh_cmd(cmd, cwd=str(self.local_repo_path))
            if result.returncode != 0:
                raise RuntimeError(f"gh CLI による PR 作成失敗:\n{result.stderr}")

            return result.stdout.strip()

    # ------------------------------------------
    # Git 操作
    # ------------------------------------------

    def _init_local_repo(self, full_repo_name: str):
        """ローカルディレクトリを Git リポジトリとして初期化し、認証情報を設定する"""
        git_dir = self.local_repo_path / ".git"
        remote_url = f"https://{self.github_user}:{self.token}@github.com/{full_repo_name}.git"
        
        if not git_dir.exists():
            self._run_git(["git", "init"])
            # 初回設定
            self._run_git(["git", "config", "user.name", "Project Forge [Bot]"])
            self._run_git(["git", "config", "user.email", "forge-bot@example.com"])
            self._run_git(["git", "remote", "add", "origin", remote_url])
            
            # main ブランチのベースを作るための空コミット
            self._run_git(["git", "commit", "--allow-empty", "-m", "Initial empty commit"])
            self._run_git(["git", "branch", "-M", self.base_branch])
            self._run_git(["git", "push", "-u", "origin", self.base_branch])
        else:
            # 既存リポジトリの場合はリモートURLのみ更新（トークン変更への対応）
            print(f"🔄 [CI/CD] リモート URL を同期中...")
            self._run_git(["git", "remote", "set-url", "origin", remote_url])
            #念の為ユーザー設定も上書き
            self._run_git(["git", "config", "user.name", "Project Forge [Bot]"])
            self._run_git(["git", "config", "user.email", "forge-bot@example.com"])

    def _git_create_branch(self, branch_name: str):
        """作業ブランチを作成してチェックアウトする"""
        self._run_git(["git", "checkout", "-b", branch_name])

    def _git_commit_and_push(self, branch_name: str, add_path: str, commit_msg: str):
        """変更のステージ・コミット・Push を行う"""
        self._run_git(["git", "add", add_path])
        # 変更がある場合のみコミット
        check = subprocess.run("git diff --staged --quiet", cwd=str(self.local_repo_path), shell=True)
        if check.returncode != 0:
            self._run_git(["git", "commit", "-m", commit_msg])
            self._run_git(["git", "push", "-u", "origin", branch_name])
        else:
            print("  [CI/CD] コミットする変更がありませんでした。")

    def _run_git(self, cmd: list):
        """git コマンドを実行する"""
        result = subprocess.run(
            cmd,
            cwd=str(self.local_repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if result.returncode != 0:
            # トークン漏洩防止
            stderr_safe = result.stderr.replace(self.token, "***")
            raise RuntimeError(f"git コマンド失敗: {cmd[0]} {' '.join(cmd[1:])}\n{stderr_safe}")

    def _run_gh_cmd(self, cmd: list, cwd: str = None) -> subprocess.CompletedProcess:
        """gh CLI コマンドを認証情報付きで実行する"""
        env = os.environ.copy()
        env["GH_TOKEN"] = self.token
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )

    # ------------------------------------------
    # ユーティリティ
    # ------------------------------------------

    def _generate_branch_name(self, brief: str) -> str:
        """ブランチ名を生成する"""
        date_str = datetime.now().strftime("%Y%m%d")
        slug = re.sub(r"[^\w\s-]", "", brief[:20]).strip()
        slug = re.sub(r"[\s_]+", "-", slug).lower()
        if not slug:
           slug = "delivery"
        return f"feature/forge-{date_str}-{slug}"

    def _build_pr_body(self, brief: str, phase_results: list) -> str:
        """PR 本文を生成する"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M JST")
        lines = [
            f"## 🤖 [AI Forge] プロジェクト納品",
            f"**案件概要**: {brief}",
            "",
            "> このリポジトリとPRは AI SIベンダーシステム「Project Forge」が自律生成しました。",
            "> レビュアーによる確認とマージをお待ちしています。",
            "",
            "### ✅ 実施フェーズと成果",
            "",
            "| フェーズ | ゲート | ターン数 | 主な成果物 |",
            "|:--------|:------:|:--------:|:---------|",
        ]

        phase_display = {
            "discovery": "🔍 Discovery",
            "design": "📐 Design",
            "build": "⚒️ Build",
            "test": "🧪 Test",
        }
        for r in phase_results:
            gate = "✅ PASS" if r.get("gate_passed", True) else "❌ FAIL"
            artifacts_list = r.get("artifacts", [])
            if artifacts_list:
                artifacts = ", ".join(f"`{a}`" for a in artifacts_list)
            else:
                artifacts = "なし"
            display = phase_display.get(r.get("phase", ""), r.get("phase", ""))
            turns = r.get("turns", "-")
            lines.append(f"| {display} | {gate} | {turns} | {artifacts} |")

        lines += [
            "",
            "### 📋 レビュアーへのお願い",
            "",
            "1. 生成された `README.md` および各ソースコードの内容を確認してください。",
            "2. 設計や要件の詳細は `artifacts/` ディレクトリ配下に格納されています。",
            "3. 問題がなければ **Approve → Squash & Merge** をお願いします。",
            "",
            "---",
            f"*🔨 Generated by Project Forge at {now}*",
        ]

        return "\n".join(lines)


# ========================
# CLI エントリポイント（テスト用）
# ========================

if __name__ == "__main__":
    """
    使用例:
        export GITHUB_TOKEN="ghp_xxxx"
        export GITHUB_USER="michael"
        python -m lib.cicd_manager
    """
    import sys

    token = os.environ.get("GITHUB_TOKEN")
    user = os.environ.get("GITHUB_USER")

    if not token or not user:
        print("Error: GITHUB_TOKEN と GITHUB_USER 環境変数を設定してください。")
        sys.exit(1)

    # テスト用のダミー実行
    print(f"CI/CD Manager テスト")
    print(f"  Token: {'*' * 10}{token[-4:]}")
    print(f"  User: {user}")
    print("  → 実際の実行は forge_orchestrator.py から --pr オプション付きで行ってください。")
