"""
test_forge_orchestrator.py - オーケストレーター機能のテスト

README.md自動生成、最終レポート生成、Pythonコード抽出などのユーティリティ関数をテストする。
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.core.forge_orchestrator import (
    _generate_final_report,
    _generate_readme,
    _extract_python_code,
    setup_project,
    PHASES,
)
from lib.core.artifact_manager import ArtifactManager
from lib.core.gemini_client import GeminiClient


def test_extract_python_code():
    """Markdownからのコード抽出を検証"""
    # 正常パターン: ```python ブロック
    md = "テキスト\n```python\nprint('hello')\n```\n他のテキスト"
    assert _extract_python_code(md) == "print('hello')"

    # 言語指定なし: ``` ブロック
    md = "テキスト\n```\ndef foo():\n    pass\n```\n他"
    assert _extract_python_code(md) == "def foo():\n    pass"

    # コードブロックが存在しない場合
    md = "プレーンテキストのみ"
    assert _extract_python_code(md) == ""

    print("✅ test_extract_python_code PASSED")


def test_setup_project():
    """プロジェクトディレクトリの初期化を検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # PROJECTS_DIR をモンキーパッチして一時ディレクトリに向ける
        import lib.core.forge_orchestrator as fo
        original = fo.PROJECTS_DIR
        fo.PROJECTS_DIR = Path(tmpdir)

        try:
            project_dir = setup_project("テスト案件: チャットボット開発")
            assert project_dir.exists(), "プロジェクトディレクトリが作成されていない"

            brief_path = project_dir / "brief.md"
            assert brief_path.exists(), "brief.md が作成されていない"

            content = brief_path.read_text(encoding='utf-8')
            assert "テスト案件" in content, "brief.md に案件概要が含まれていない"
        finally:
            fo.PROJECTS_DIR = original

    print("✅ test_setup_project PASSED")


def test_phases_definition():
    """フェーズ定義が正しいことを検証"""
    assert len(PHASES) == 4, f"4フェーズを期待: 実際は {len(PHASES)}"

    phase_names = [p["name"] for p in PHASES]
    assert phase_names == ["discovery", "design", "build", "test"], \
        f"フェーズ順序が不正: {phase_names}"

    # 各フェーズに必須フィールドがあること
    for phase in PHASES:
        assert "name" in phase, "name フィールドがない"
        assert "display_name" in phase, "display_name フィールドがない"
        assert "goal" in phase, "goal フィールドがない"

    print("✅ test_phases_definition PASSED")


def test_generate_final_report():
    """最終レポート生成を検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # PhaseResult相当のモックオブジェクトを作成
        mock_result = MagicMock()
        mock_result.phase_name = "discovery"
        mock_result.gate_passed = True
        mock_result.artifacts = {"requirements.md": "内容"}
        mock_result.log = [
            {"turn": 1, "speaker": "PM", "speaker_key": "pm", "message": "テスト発言のテキスト内容です。"},
        ]

        _generate_final_report(project_dir, "テスト案件", [mock_result])

        report_path = project_dir / "FINAL_REPORT.md"
        assert report_path.exists(), "FINAL_REPORT.md が生成されていない"

        content = report_path.read_text(encoding='utf-8')
        assert "テスト案件" in content, "案件概要が含まれていない"
        assert "Discovery" in content, "フェーズ名が含まれていない"
        assert "✅ 通過" in content, "ゲート結果が含まれていない"

    print("✅ test_generate_final_report PASSED")


def test_generate_readme_mock():
    """README.md生成がモックモードで正しく動作することを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        gemini = GeminiClient(mock_mode=True)
        manager = ArtifactManager(project_dir)

        # テスト用の成果物を作成
        manager.save_artifact("discovery", "requirements.md", "# 要件\n- 認証機能")
        manager.save_artifact("design", "architecture.md", "# 設計\n- モジュール構成")

        _generate_readme(project_dir, "テスト案件: AI ナレッジベース", gemini, manager)

        readme_path = project_dir / "README.md"
        assert readme_path.exists(), "README.md が生成されていない"

        content = readme_path.read_text(encoding='utf-8')
        assert len(content) > 0, "README.md が空"

    print("✅ test_generate_readme_mock PASSED")


def test_generate_readme_error_handling():
    """README.md生成失敗時にプロセスが停止しないことを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        manager = ArtifactManager(project_dir)

        # generate() で例外を投げるモッククライアント
        gemini = MagicMock()
        gemini.generate.side_effect = RuntimeError("API Error")

        # 例外が外に漏れないことを確認
        _generate_readme(project_dir, "テスト案件", gemini, manager)

        # README.md は作成されないが、プロセスは正常に通過する
        readme_path = project_dir / "README.md"
        assert not readme_path.exists(), "エラー時にREADME.mdが作成されるべきではない"

    print("✅ test_generate_readme_error_handling PASSED")


if __name__ == "__main__":
    test_extract_python_code()
    test_setup_project()
    test_phases_definition()
    test_generate_final_report()
    test_generate_readme_mock()
    test_generate_readme_error_handling()
    print("\n🏯 All forge_orchestrator tests PASSED!")
