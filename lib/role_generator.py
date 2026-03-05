"""
role_generator.py - 案件概要からAIロール（エージェント）を生成するモジュール

Discussion Engineの persona_generator.py のパターンを踏襲。
違い:
  - 議論の「スタンス」ではなく、開発チームとしての「責務」と「専門性」を定義
  - テンプレートベース（templates/roles/）で役割を固定し、案件ごとの文脈を注入
  - フェーズごとに参加するロールが異なる
"""

import json
from pathlib import Path

# ロール絵文字マッピング
ROLE_EMOJIS = {
    "pm": "📋",
    "ba": "🔍",
    "architect": "🏗️",
    "qa": "🧪",
    "developer": "⌨️",
}

# 各フェーズに参加するロール定義
PHASE_PARTICIPANTS = {
    "discovery": ["pm", "ba", "architect"],
    "design": ["pm", "architect", "qa"],
    "build": ["pm", "developer", "architect"],
    "test": ["pm", "developer", "qa"],
}

# ロールの表示名と絵文字
ROLE_DISPLAY_NAMES = {
    "pm": {"name": "PM（プロジェクトマネージャー）", "emoji": "📋"},
    "ba": {"name": "BA（ビジネスアナリスト）", "emoji": "🔍"},
    "architect": {"name": "Architect（アーキテクト）", "emoji": "🏗️"},
    "qa": {"name": "QA（品質保証エンジニア）", "emoji": "🧪"},
    "developer": {"name": "Developer（開発者）", "emoji": "⌨️"},
}


def get_phase_participants(phase_name: str) -> list:
    """
    指定フェーズに参加するロール名のリストを返す。

    Args:
        phase_name: フェーズ名（"discovery", "design", "build", "test"）
    Returns:
        list: ロールキーのリスト（例: ["pm", "ba", "architect"]）
    """
    return PHASE_PARTICIPANTS.get(phase_name, [])


def setup_roles(agents_dir: Path, project_brief: str, phase_name: str, templates_dir: Path = None) -> dict:
    """
    指定フェーズの参加ロールに対して、エージェントディレクトリとINSTRUCTIONS.mdを生成する。

    Args:
        agents_dir: エージェント設定を保存するディレクトリ
        project_brief: 案件概要テキスト
        phase_name: フェーズ名
        templates_dir: テンプレート格納ディレクトリ（デフォルト: ../templates）
    Returns:
        dict: {ロールキー: {"name": 表示名, "role": ロールキー, "emoji": 絵文字, "dir": ディレクトリパス, "system_instruction": 指示テキスト}}
    """
    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent / "templates"
    
    participants = get_phase_participants(phase_name)
    roles = {}
    
    agents_dir.mkdir(parents=True, exist_ok=True)
    
    for role_key in participants:
        display_name = ROLE_DISPLAY_NAMES.get(role_key, role_key)
        emoji = ROLE_EMOJIS.get(role_key, "👤")
        
        # テンプレートを読み込み、案件概要を注入
        template_path = templates_dir / "roles" / f"{role_key}.md"
        if template_path.exists():
            template_content = template_path.read_text(encoding='utf-8')
            instruction = template_content.replace("{project_brief}", project_brief)
        else:
            # テンプレートがない場合はデフォルト指示を生成
            instruction = _generate_default_instruction(display_name, role_key, project_brief)
        
        # エージェントディレクトリ作成
        role_dir = agents_dir / role_key
        role_dir.mkdir(parents=True, exist_ok=True)
        
        # INSTRUCTIONS.md 書き出し
        (role_dir / "INSTRUCTIONS.md").write_text(instruction, encoding='utf-8')
        
        roles[role_key] = {
            "name": display_name,
            "role": role_key,
            "emoji": emoji,
            "dir": str(role_dir),
            "system_instruction": instruction,
        }
        print(f"  [+] {emoji} {display_name} をセットアップしました")
    
    print(f"[+] {len(roles)} ロールのセットアップ完了 (Phase: {phase_name})")
    return roles


def _generate_default_instruction(display_name: str, role_key: str, project_brief: str) -> str:
    """テンプレートが存在しない場合のデフォルト指示を生成"""
    return f"""# System Instructions for {display_name}

## 案件
"{project_brief}"

## あなたの役割
あなたは {display_name} として、このプロジェクトに参加しています。
あなたの専門知識を活かし、プロジェクトの成功に貢献してください。

## 行動指針
1. 自分の専門領域について積極的に発言する
2. 他メンバーの意見を尊重しつつ、必要に応じて建設的な反論をする
3. プロジェクトの品質向上に貢献する
"""


def get_role_info(role_key: str) -> dict:
    """ロール情報を取得するヘルパー"""
    return {
        "name": ROLE_DISPLAY_NAMES.get(role_key, role_key),
        "emoji": ROLE_EMOJIS.get(role_key, "👤"),
    }
