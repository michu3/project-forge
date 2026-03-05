"""
test_role_generator.py - ロール生成モジュールのテスト
"""

import sys
import shutil
import tempfile
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.core.role_generator import (
    setup_roles,
    get_phase_participants,
    get_role_info,
    PHASE_PARTICIPANTS,
    ROLE_DISPLAY_NAMES,
)


def test_phase_participants():
    """各フェーズの参加者が正しく定義されていることを確認"""
    # Discovery: PM, BA, Architect
    participants = get_phase_participants("discovery")
    assert "pm" in participants, "discoveryにPMがいない"
    assert "ba" in participants, "discoveryにBAがいない"
    assert "architect" in participants, "discoveryにArchitectがいない"
    assert "qa" not in participants, "discoveryにQAが含まれている（不正）"
    
    # Design: PM, Architect, QA
    participants = get_phase_participants("design")
    assert "pm" in participants, "designにPMがいない"
    assert "architect" in participants, "designにArchitectがいない"
    assert "qa" in participants, "designにQAがいない"
    assert "ba" not in participants, "designにBAが含まれている（不正）"
    
    # Build: PM, Developer, Architect
    participants = get_phase_participants("build")
    assert "pm" in participants, "buildにPMがいない"
    assert "developer" in participants, "buildにDeveloperがいない"
    assert "architect" in participants, "buildにArchitectがいない"
    
    # Test: PM, Developer, QA
    participants = get_phase_participants("test")
    assert "pm" in participants, "testにPMがいない"
    assert "developer" in participants, "testにDeveloperがいない"
    assert "qa" in participants, "testにQAがいない"
    
    print("✅ test_phase_participants PASSED")


def test_unknown_phase():
    """未定義フェーズに対して空リストが返ることを確認"""
    participants = get_phase_participants("unknown_phase")
    assert participants == [], f"未定義フェーズで空リスト以外が返った: {participants}"
    print("✅ test_unknown_phase PASSED")


def test_setup_roles_discovery():
    """Discovery フェーズのロールセットアップを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir) / "agents"
        templates_dir = Path(__file__).parent.parent / "templates"
        
        roles = setup_roles(
            agents_dir=agents_dir,
            project_brief="テスト案件: 社内チャットボットの開発",
            phase_name="discovery",
            templates_dir=templates_dir,
        )
        
        # 3ロール（PM, BA, Architect）が生成されること
        assert len(roles) == 3, f"期待: 3ロール, 実際: {len(roles)}"
        assert "pm" in roles, "PMが生成されていない"
        assert "ba" in roles, "BAが生成されていない"
        assert "architect" in roles, "Architectが生成されていない"
        
        # 各ロールの必須フィールド
        for key, role in roles.items():
            assert "name" in role, f"{key}: name がない"
            assert "emoji" in role, f"{key}: emoji がない"
            assert "dir" in role, f"{key}: dir がない"
            assert "system_instruction" in role, f"{key}: system_instruction がない"
            
            # INSTRUCTIONS.md が作成されていること
            inst_path = Path(role["dir"]) / "INSTRUCTIONS.md"
            assert inst_path.exists(), f"{key}: INSTRUCTIONS.md が作成されていない"
            
            # 案件概要がINSTRUCTIONSに含まれていること
            content = inst_path.read_text(encoding='utf-8')
            assert "テスト案件" in content, f"{key}: 案件概要がINSTRUCTIONSに反映されていない"
    
    print("✅ test_setup_roles_discovery PASSED")


def test_setup_roles_design():
    """Design フェーズのロールセットアップを検証"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = Path(tmpdir) / "agents"
        templates_dir = Path(__file__).parent.parent / "templates"
        
        roles = setup_roles(
            agents_dir=agents_dir,
            project_brief="テスト案件",
            phase_name="design",
            templates_dir=templates_dir,
        )
        
        # 3ロール（PM, Architect, QA）が生成されること
        assert len(roles) == 3, f"期待: 3ロール, 実際: {len(roles)}"
        assert "pm" in roles
        assert "architect" in roles
        assert "qa" in roles
        assert "ba" not in roles, "designフェーズにBAが含まれている"
    
    print("✅ test_setup_roles_design PASSED")


def test_role_info():
    """ロール情報ヘルパーの検証"""
    info = get_role_info("developer")
    
    # role_generator.py の get_role_info は以下の形式を返す
    # { "name": {"name": "...", "emoji": "..."}, "emoji": "..." }
    #ROLE_DISPLAY_NAMESの仕様変更（辞書型へ）に伴う修正
    assert "Developer" in info["name"]["name"] if isinstance(info["name"], dict) else info["name"]
    
    info = get_role_info("unknown")
    assert info["emoji"] == "👤"  # デフォルト絵文字
    
    print("✅ test_role_info PASSED")


if __name__ == "__main__":
    test_phase_participants()
    test_unknown_phase()
    test_setup_roles_discovery()
    test_setup_roles_design()
    test_role_info()
    print("\n🏯 All role_generator tests PASSED!")
