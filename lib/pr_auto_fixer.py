import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass

# 既存モジュールのインポート
try:
    from lib.gemini_client import GeminiClient
    from lib.phase_engine import PhaseEngine, PhaseResult
    from lib.artifact_manager import ArtifactManager
except ImportError:
    # 実行場所（GitHub Actions 等）に応じたパス調整
    sys.path.append(str(Path(__file__).parent.parent))
    from lib.gemini_client import GeminiClient
    from lib.phase_engine import PhaseEngine, PhaseResult
    from lib.artifact_manager import ArtifactManager

@dataclass
class ReviewComment:
    body: str
    file_path: Optional[str] = None
    line: Optional[int] = None
    diff_hunk: Optional[str] = None

class PRAutoFixer:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.gemini = GeminiClient()
        self.artifact_manager = ArtifactManager(repo_path / "projects" / "current_fix")
        
    def run_from_env(self):
        """環境変数から情報を取得して修正実行 (GitHub Actions用)"""
        pr_number = os.getenv("PR_NUMBER")
        comment_body = os.getenv("COMMENT_BODY")
        repo_name = os.getenv("REPO")
        branch = os.getenv("BRANCH")

        if not all([pr_number, comment_body, repo_name, branch]):
            print("❌ 必要な環境変数が不足しています。")
            return

        print(f"🚀 PR #{pr_number} への修正を開始します: {comment_body}")
        
        # 1. コマンド抽出 (@forge fix: ...)
        instruction = self._extract_instruction(comment_body)
        if not instruction:
            print("⏭️ '@forge fix:' プレフィックスがないためスキップします。")
            return

        # 2. 修正規模の分類
        classification = self._classify_comment(instruction)
        print(f"📊 修正規模分類: {classification}")

        # 3. 修正の実行 (ミニフェーズ)
        success = self._execute_fix(classification, instruction)

        if success:
            # 4. Commit & Push
            self._push_changes(branch)
            # 5. 結果レポート作成
            self._post_result_to_pr(pr_number, classification)
        else:
            print("❌ 修正に失敗しました。")

    def _extract_instruction(self, body: str) -> Optional[str]:
        prefix = "@forge fix:"
        if prefix in body:
            return body.split(prefix)[1].strip()
        return None

    def _classify_comment(self, instruction: str) -> str:
        prompt = f"""
        以下のレビューコメント（修正指示）の規模を、SIMPLE, MODERATE, COMPLEX のいずれかに分類してください。

        指示: 「{instruction}」

        - SIMPLE: 軽微な修正（typo, 命名変更, コメント追加, 1行程度の変更）
        - MODERATE: ロジック修正（関数追加, エラーハンドリング, 条件分岐の追加）
        - COMPLEX: 設計変更（クラス構成の変更, インターフェースの変更, 大規模なリファクタリング）

        回答は分類名（SIMPLE/MODERATE/COMPLEX）のみを返してください。
        """
        response = self.gemini.generate(prompt)
        content = response.strip().upper()
        for c in ["SIMPLE", "MODERATE", "COMPLEX"]:
            if c in content:
                return c
        return "MODERATE"

    def _execute_fix(self, classification: str, instruction: str) -> bool:
        """修正の実行 (ミニフェーズ)"""
        print(f"🛠️ {classification} 規模の修正を実行中...")
        
        # 1. 参加者の決定
        participants = self._get_participants(classification)
        
        # 2. コードコンテキストの取得 (TODO: gh api でコメント箇所のコードを取得)
        code_context = self._get_code_context()
        
        # 3. PhaseEngine の実行
        engine = PhaseEngine(self.gemini, max_turns=5, min_turns=1)
        goal = f"レビューコメントに基づくコードの修正: {instruction}"
        
        # コンテキストに「現在の全量」を明示
        input_context = f"--- 修正指示 ---\n{instruction}\n\n--- 修正対象コード周辺 (Context) ---\n{code_context}\n\n重要: 修正後のファイルは、一部の抜粋ではなく、ファイル全体の最新の内容を source_code.md として出力してください。"
        
        result = engine.run_phase(
            phase_name=f"fix_{classification.lower()}",
            roles=participants,
            phase_goal=goal,
            input_context=input_context,
            artifact_manager=self.artifact_manager
        )
        
        if result.gate_passed:
            # 成果物（修正後のコード）をファイルに適用する
            self._apply_fix_artifacts(result.artifacts)
            return True
        return False

    def _get_participants(self, classification: str) -> Dict:
        """修正規模に応じたペルソナをセットアップする"""
        from lib.role_generator import ROLE_DISPLAY_NAMES, ROLE_EMOJIS
        
        roles = ["pm", "developer"]
        if classification == "MODERATE":
            roles = ["pm", "architect", "developer", "qa"]
        elif classification == "COMPLEX":
            roles = ["pm", "architect", "developer", "qa", "ba"]
            
        full_roles = {}
        templates_dir = Path(__file__).parent.parent / "templates"
        
        for r in roles:
            # テンプレートから読み込み
            template_path = templates_dir / "roles" / f"{r}.md"
            if template_path.exists():
                instruction = template_path.read_text(encoding="utf-8")
                # 必要に応じてプレースホルダーを置換
                instruction = instruction.replace("{project_brief}", os.getenv("COMMENT_BODY", ""))
            else:
                instruction = f"You are the {r} in the project. Please help fix the issue."
                
            full_roles[r] = {
                "name": ROLE_DISPLAY_NAMES.get(r, {"name": r.upper()})["name"],
                "emoji": ROLE_EMOJIS.get(r, "🤖"),
                "system_instruction": instruction
            }
        return full_roles

    def _get_comment_details(self) -> Dict:
        """gh api を使ってコメントの詳細を取得する"""
        comment_id = os.getenv("COMMENT_ID")
        if not comment_id:
            return {}
        
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{os.getenv('REPO')}/pulls/comments/{comment_id}"],
                capture_output=True, text=True, encoding="utf-8"
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception as e:
            print(f"⚠️ コメント詳細の取得に失敗: {e}")
        return {}

    def _get_code_context(self) -> str:
        """指摘箇所のコードを gh CLI や git で取得する"""
        details = self._get_comment_details()
        if not details:
            return "(No specific code context could be retrieved)"
        
        path = details.get("path")
        diff_hunk = details.get("diff_hunk")
        
        context = f"File: {path}\n\nDiff Context:\n{diff_hunk}\n"
        
        # 実際のファイルの中身も読めたら読む
        file_path = self.repo_path / path
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                # 前後数行を抜き出す等の工夫ができるが、ひとまず全量渡す（大規模な場合は注意）
                context += f"\nFull Content of {path}:\n{content[:5000]}"
            except Exception:
                pass
                
        return context

    def _apply_fix_artifacts(self, artifacts: Dict[str, str]):
        """生成された成果物（修正コード）を実際のファイル名にマッピングして保存する"""
        import re
        source_md = artifacts.get("source_code.md", "")
        if not source_md:
            print("⚠️ source_code.md が成果物に含まれていません。")
            return

        # forge_orchestrator.py の展開ロジックを流用
        sections = re.split(r'\n###\s+', '\n' + source_md)
        deployed_count = 0
        
        for section in sections:
            if not section.strip():
                continue
                
            lines = section.strip().split('\n')
            header = lines[0]
            # より柔軟な正規表現: ### [MODIFY] path/to/file.py や #### File: path/to/file.py 等に対応
            name_match = re.search(r'([a-zA-Z0-9_\-\./]+\.[a-z]+)', header)
            if not name_match:
                # ヘッダーにない場合、セクション全体から最初のパスっぽいものを探す
                name_match = re.search(r'(?:File|Path|Target):\s*([a-zA-Z0-9_\-\./]+\.[a-z]+)', section, re.I)
                if not name_match:
                    continue
                
            rel_path_str = name_match.group(1)
            code_match = re.search(r'```(?:[a-z]+)?\s*\n(.*?)\n```', section, re.DOTALL)
            if not code_match:
                continue
                
            content = code_match.group(1).strip()
            rel_path = Path(rel_path_str.strip())
            
            if ".." in rel_path_str or rel_path.is_absolute():
                continue
                
            full_path = self.repo_path / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            print(f"  [+] {rel_path} を修正適用しました")
            deployed_count += 1
        
        print(f"✅ {deployed_count} 個のファイルを修正適用完了")

    def _push_changes(self, branch: str):
        """修正したコードを GitHub に Push する"""
        print(f"⬆️ 成果物を Push します: {branch}")
        token = os.getenv("GITHUB_TOKEN")
        repo = os.getenv("REPO")
        
        # 認証付きリモートURLの設定
        remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        
        subprocess.run(["git", "config", "user.name", "Project Forge [Bot]"], cwd=self.repo_path)
        subprocess.run(["git", "config", "user.email", "forge-bot@example.com"], cwd=self.repo_path)
        
        subprocess.run(["git", "add", "."], cwd=self.repo_path)
        result = subprocess.run(
            ["git", "commit", "-m", f"[🤖 Forge] Auto-fix by review comment: {os.getenv('COMMENT_ID')}"],
            cwd=self.repo_path, capture_output=True, text=True
        )
        if "nothing to commit" in result.stdout:
            print("ℹ️ 変更がないため Push をスキップします。")
            return

        subprocess.run(["git", "push", remote_url, f"HEAD:{branch}"], cwd=self.repo_path)

    def _post_result_to_pr(self, pr_number: str, classification: str):
        """PR に詳細なレポートを投稿する"""
        participants_map = {
            "SIMPLE": "⚒️ Developer",
            "MODERATE": "🏗️ Architect → ⚒️ Developer → 🧪 QA",
            "COMPLEX": "📋 PM → 🏗️ Architect → ⚒️ Developer → 🧪 QA"
        }
        participants = participants_map.get(classification, classification)
        
        body = f"""## ✅ Project Forge 自動修正完了

| 項目 | 内容 |
|:---|:---|
| 修正規模 | **{classification}** |
| 参加ペルソナ | {participants} |
| 指示コメント | {os.getenv('COMMENT_BODY')} |

指示に基づきコードを修正し、最新のコミットとしてプッシュしました。
内容の確認をお願いします。

---
*Generated by Project Forge Feedback Loop*"""
        
        subprocess.run(["gh", "pr", "comment", pr_number, "--body", body], cwd=self.repo_path)

if __name__ == "__main__":
    fixer = PRAutoFixer(Path("."))
    fixer.run_from_env()
