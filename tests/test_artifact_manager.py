"""
test_artifact_manager.py - 成果物管理モジュールのテスト
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.artifact_manager import ArtifactManager


def test_save_and_load():
    """成果物の保存と読み込みが正しく動作することを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ArtifactManager(Path(tmpdir))
        
        # 保存
        content = "# 要件定義書\n\n## 機能要件\n- ユーザー認証\n- チャット機能"
        path = manager.save_artifact("discovery", "requirements.md", content)
        
        assert path.exists(), "保存先ファイルが存在しない"
        
        # 読み込み
        loaded = manager.load_artifact("discovery", "requirements.md")
        assert loaded == content, "保存内容と読込内容が一致しない"
    
    print("✅ test_save_and_load PASSED")


def test_load_phase_artifacts():
    """フェーズ全成果物の一括読み込みを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ArtifactManager(Path(tmpdir))
        
        manager.save_artifact("discovery", "requirements.md", "要件")
        manager.save_artifact("discovery", "risks.md", "リスク")
        
        artifacts = manager.load_phase_artifacts("discovery")
        assert len(artifacts) == 2, f"期待: 2件, 実際: {len(artifacts)}"
        assert "requirements.md" in artifacts
        assert "risks.md" in artifacts
    
    print("✅ test_load_phase_artifacts PASSED")


def test_load_nonexistent():
    """存在しない成果物の読み込みでエラーが発生することを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ArtifactManager(Path(tmpdir))
        
        try:
            manager.load_artifact("discovery", "nonexistent.md")
            assert False, "FileNotFoundErrorが発生しなかった"
        except FileNotFoundError:
            pass  # 期待通り
    
    print("✅ test_load_nonexistent PASSED")


def test_input_context_discovery():
    """Discoveryフェーズの入力コンテキスト（brief.md）を検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        
        # brief.md を作成
        (project_dir / "brief.md").write_text("テスト案件の概要です", encoding='utf-8')
        
        manager = ArtifactManager(project_dir)
        context = manager.get_input_context("discovery")
        
        assert "テスト案件の概要" in context, "briefの内容が含まれていない"
    
    print("✅ test_input_context_discovery PASSED")


def test_input_context_design():
    """Designフェーズの入力コンテキスト（前フェーズ成果物）を検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ArtifactManager(Path(tmpdir))
        
        # Phase 1 の成果物を保存
        manager.save_artifact("discovery", "requirements.md", "# 要件\n- 認証機能")
        
        # Phase 2 の入力コンテキスト取得
        context = manager.get_input_context("design")
        assert "要件" in context, "前フェーズの成果物が含まれていない"
        assert "認証機能" in context, "前フェーズの内容が含まれていない"
    
    print("✅ test_input_context_design PASSED")


def test_list_artifacts():
    """成果物一覧の取得を検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ArtifactManager(Path(tmpdir))
        
        manager.save_artifact("discovery", "requirements.md", "要件")
        manager.save_artifact("design", "architecture.md", "設計")
        
        listing = manager.list_artifacts()
        assert "discovery" in listing
        assert "design" in listing
        assert "requirements.md" in listing["discovery"]
        assert "architecture.md" in listing["design"]
    
    print("✅ test_list_artifacts PASSED")


def test_manifest():
    """マニフェスト（メタデータ）が正しく保存されることを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ArtifactManager(Path(tmpdir))
        
        manager.save_artifact("discovery", "requirements.md", "要件")
        
        # マニフェストファイルが存在すること
        assert manager.manifest_path.exists(), "manifest.jsonが作成されていない"
        
        # メタデータが正しいこと
        manifest = manager._load_manifest()
        key = "discovery/requirements.md"
        assert key in manifest, "マニフェストにエントリがない"
        assert manifest[key]["phase"] == "discovery"
        assert "created_at" in manifest[key]
    
    print("✅ test_manifest PASSED")


if __name__ == "__main__":
    test_save_and_load()
    test_load_phase_artifacts()
    test_load_nonexistent()
    test_input_context_discovery()
    test_input_context_design()
    test_list_artifacts()
    test_manifest()
    print("\n🏯 All artifact_manager tests PASSED!")
