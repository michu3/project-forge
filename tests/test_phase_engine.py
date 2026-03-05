"""
test_phase_engine.py - フェーズ進行エンジンのテスト

モックモードを使用し、実際のGemini APIは呼び出さない。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.phase_engine import PhaseEngine
from lib.gemini_client import GeminiClient


def test_eagerness_parse():
    """Eagernessスコアのパースを検証"""
    engine = PhaseEngine(GeminiClient(mock_mode=True))
    
    # 正常なフォーマット
    assert engine._parse_eagerness("[Eagerness: 85] 議論したい") == 85
    assert engine._parse_eagerness("[Eagerness: 0] 特にない") == 0
    assert engine._parse_eagerness("[Eagerness: 100] 非常に重要") == 100
    
    # スコアが見つからない場合
    assert engine._parse_eagerness("スコアなし") == 50
    
    # 範囲外の値はクランプされる
    assert engine._parse_eagerness("[Eagerness: 150]") == 100
    assert engine._parse_eagerness("[Eagerness: -10]") == 50  # 負数はパースされない
    
    print("✅ test_eagerness_parse PASSED")


def test_gate_tag_check():
    """ゲートタグの検出を検証"""
    engine = PhaseEngine(GeminiClient(mock_mode=True))
    
    # ゲート通過
    assert engine._check_gate_tag("十分です。[GATE_PASSED: true]") == True
    assert engine._check_gate_tag("[GATE_PASSED:true]") == True
    assert engine._check_gate_tag("blah [GATE_PASSED: True] blah") == True
    
    # ゲート不通過
    assert engine._check_gate_tag("まだ不十分です") == False
    assert engine._check_gate_tag("[GATE_PASSED: false]") == False
    assert engine._check_gate_tag("") == False
    
    print("✅ test_gate_tag_check PASSED")


def test_format_log():
    """ログフォーマットを検証"""
    history = [
        {"turn": 1, "speaker": "BA", "speaker_key": "ba", "message": "要件1"},
        {"turn": 2, "speaker": "Architect", "speaker_key": "architect", "message": "技術検討"},
        {"turn": 3, "speaker": "PM", "speaker_key": "pm", "message": "まとめ"},
    ]
    
    # 全件フォーマット
    formatted = PhaseEngine._format_log(history)
    assert "BA" in formatted
    assert "Architect" in formatted
    assert "PM" in formatted
    
    # 直近2件のみ
    formatted = PhaseEngine._format_log(history, limit=2)
    assert "BA" not in formatted  # 1件目は含まれない
    assert "Architect" in formatted
    assert "PM" in formatted
    
    # 空ログ
    formatted = PhaseEngine._format_log([])
    assert "まだ議論は始まっていません" in formatted
    
    print("✅ test_format_log PASSED")


def test_phase_artifacts_definition():
    """フェーズ成果物の定義が正しいことを検証"""
    # Discovery
    assert "requirements.md" in PhaseEngine.PHASE_ARTIFACTS["discovery"]
    assert "risks.md" in PhaseEngine.PHASE_ARTIFACTS["discovery"]
    
    # Design
    assert "architecture.md" in PhaseEngine.PHASE_ARTIFACTS["design"]
    assert "test_strategy.md" in PhaseEngine.PHASE_ARTIFACTS["design"]
    
    # Build
    assert "source_code.md" in PhaseEngine.PHASE_ARTIFACTS["build"]
    assert "implementation_notes.md" in PhaseEngine.PHASE_ARTIFACTS["build"]

    # Test
    assert "test_scripts.md" in PhaseEngine.PHASE_ARTIFACTS["test"]
    assert "test_report.md" in PhaseEngine.PHASE_ARTIFACTS["test"]
    
    print("✅ test_phase_artifacts_definition PASSED")


def test_gate_criteria_definition():
    """ゲート基準が定義されていることを検証"""
    assert "discovery" in PhaseEngine.GATE_CRITERIA
    assert "design" in PhaseEngine.GATE_CRITERIA
    assert "build" in PhaseEngine.GATE_CRITERIA
    assert "test" in PhaseEngine.GATE_CRITERIA
    assert "機能要件" in PhaseEngine.GATE_CRITERIA["discovery"]
    assert "テスト戦略" in PhaseEngine.GATE_CRITERIA["design"]
    assert "ソースコード" in PhaseEngine.GATE_CRITERIA["build"]
    assert "受入基準" in PhaseEngine.GATE_CRITERIA["test"]
    
    print("✅ test_gate_criteria_definition PASSED")


if __name__ == "__main__":
    test_eagerness_parse()
    test_gate_tag_check()
    test_format_log()
    test_phase_artifacts_definition()
    test_gate_criteria_definition()
    print("\n🏯 All phase_engine tests PASSED!")
