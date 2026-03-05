import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# パス追加
sys.path.append(str(Path(__file__).parent))
from lib.cicd.pr_auto_fixer import PRAutoFixer

def test_local_fix_logic():
    """
    GitHub Actions などの環境をモックして、
    ローカルで修正ロジックコード生成・適用までの流れを確認する。
    ※ 実際の Push や GitHub API 呼び出しはモック。
    """
    print("🧪 Phase 7: Local Validation Start")
    
    # ワークスペース準備
    test_repo = Path(__file__).parent / "projects" / "test_fix_workspace"
    test_repo.mkdir(parents=True, exist_ok=True)
    
    # テスト用ファイルの作成
    sample_file = test_repo / "main.py"
    sample_file.write_text("def hello():\n    print('Hello World')\n", encoding="utf-8")
    
    # モック環境変数
    env = {
        "PR_NUMBER": "123",
        "COMMENT_BODY": "@forge fix: main.py の print 文字列を 'Hello Project Forge' に変更して",
        "REPO": "user/test-repo",
        "BRANCH": "feature/test",
        "COMMENT_ID": "999"
    }

    with patch.dict(os.environ, env):
        fixer = PRAutoFixer(test_repo)
        
        # GitHub API 依存部分をモック
        fixer._get_comment_details = MagicMock(return_value={
            "path": "main.py",
            "diff_hunk": "@@ -0,0 +1,2 @@\n+def hello():\n+    print('Hello World')"
        })
        fixer._push_changes = MagicMock()
        fixer._post_result_to_pr = MagicMock()
        
        # 修正実行
        print("🛠️  Running fix...")
        fixer.run_from_env()
        
        # 検証: main.py が更新されているか
        updated_content = sample_file.read_text(encoding="utf-8")
        print(f"📄 Updated content of main.py:\n{updated_content}")
        
        if "Hello Project Forge" in updated_content:
            print("✅ Validation Success: Code was correctly updated by Forge.")
        else:
            print("❌ Validation Failed: Code was not updated as expected.")

if __name__ == "__main__":
    test_local_fix_logic()
