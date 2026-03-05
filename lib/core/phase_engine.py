"""
phase_engine.py - フェーズ進行エンジン

Discussion Engineの DiscussionEngine クラスに相当する、
Project Forgeの中核エンジン。

主な違い:
  - フェーズごとに参加エージェントとゴールが異なる
  - ターンループ終了後にゲートチェック（品質判定）を行う
  - 成果物の生成・保存をフェーズ終了時に行う
"""

import json
import re
import time
import concurrent.futures
from pathlib import Path
from .gemini_client import GeminiClient
from .artifact_manager import ArtifactManager

# エージェントの自発性評価用プロンプト
EAGERNESS_PROMPT = """あなたは今、以下のプロジェクトチームの一員として議論に参加しています。

あなたの役割:
{system_instruction}

---
現在の議論の流れ（直近の発言）:
{recent_log}
---

この議論に対し、あなたがどれだけ発言したいかを0〜100のスコアで評価してください。
- 100: 非常に重要な指摘や提案がある
- 70-99: 議論に貢献できる意見がある
- 30-69: 補足程度
- 0-29: 今は他のメンバーに任せたい

以下のフォーマットで回答してください:
[Eagerness: スコア] 理由を一行で"""


# フェーズ議論用プロンプト
DISCUSSION_PROMPT = """あなたのロール:
{system_instruction}

---
フェーズの目標:
{phase_goal}

---
入力情報（前フェーズの成果物等）:
{input_context}

---
これまでの議論ログ:
{full_log}

---
上記の文脈を踏まえ、あなたの専門的な立場から発言してください。
他メンバーの意見に対して、賛成・反論・補足を述べてください。
具体的で建設的な内容を心がけてください。"""


# ゲートチェック用プロンプト（PMが実行）
GATE_CHECK_PROMPT = """あなたはPM（プロジェクトマネージャー）です。

これまでの議論ログ:
{full_log}

---
このフェーズ（{phase_name}）のゲート基準:
{gate_criteria}

---
上記の議論内容を踏まえ、ゲート基準が満たされているかを判定してください。

判定結果を以下のフォーマットで発言してください:
- ゲート通過の場合: 判定理由を述べた後、発言の末尾に [GATE_PASSED: true] を含めてください
- ゲート不通過の場合: 不足している点を具体的に指摘し、議論の継続を促してください"""


# 成果物生成用プロンプト
ARTIFACT_PROMPT = """以下の議論ログを元に、{artifact_name} を作成してください。

議論ログ:
{full_log}

---
入力情報:
{input_context}

---
成果物の要件:
{artifact_description}

Markdownフォーマットで出力してください。"""


class PhaseResult:
    """フェーズ実行結果"""
    def __init__(self, phase_name: str, gate_passed: bool, artifacts: dict, log: list):
        self.phase_name = phase_name
        self.gate_passed = gate_passed
        self.artifacts = artifacts  # {filename: content}
        self.log = log


class PhaseEngine:
    """
    フェーズ進行を制御するエンジン。
    
    各フェーズで以下を実行:
    1. 参加ロールのセットアップ
    2. ターンループ（議論）
    3. ゲートチェック（品質判定）
    4. 成果物生成
    """
    
    # フェーズごとのゲート基準
    GATE_CRITERIA = {
        "discovery": "要件（機能要件、非機能要件、スコープ）が明確に定義され、リスクが洗い出されているか",
        "design": "要件に基づくアーキテクチャ設計と、テスト戦略が具体的に策定されているか",
        "build": "設計に基づく具体的なソースコードや構成ファイルが実装され、レビューを通過しているか",
        "test": "テスト戦略に基づいたテストコード・スクリプトが実装され、受入基準を満たしている（または課題が明確になっている）か",
        "fix_simple": "指摘された軽微な修正が正しくコードに反映されているか",
        "fix_moderate": "指摘されたロジックの修正が正しく反映され、整合性が保たれているか",
        "fix_complex": "指摘された設計変更が適切に行われ、システム全体の整合性が保たれているか",
    }
    
    # フェーズごとの生成成果物定義
    PHASE_ARTIFACTS = {
        "discovery": {
            "requirements.md": "プロジェクトの要件定義書。機能要件（ユーザーストーリー形式）、非機能要件、スコープ定義、前提条件を含む。",
            "risks.md": "プロジェクトのリスク一覧。リスク項目、影響度、発生確率、対策案を含む。",
        },
        "design": {
            "architecture.md": "システム設計書。システム構成図、技術スタック、データモデル、API設計、非機能設計を含む。",
            "test_strategy.md": "テスト戦略書。テスト種別、テスト範囲、優先度、テストケース概要を含む。",
        },
        "build": {
            "source_code.md": "実装された主要なソースコード、構成ファイル、ディレクトリ構造。具体的なコードブロックを含むこと。",
            "implementation_notes.md": "実装上の工夫、技術的負債、アーキテクチャ設計からの変更点や妥協点をまとめたドキュメント。",
        },
        "test": {
            "test_scripts.md": "実装されたテストコード、テスト実行スクリプト、テストデータの定義。",
            "test_report.md": "テスト実行結果（シミュレーション）、エッジケースの検証結果、QAによる品質評価レポート。",
        },
        "fix_simple": {
            "source_code.md": "修正・改善されたソースコード。指摘箇所が正しく修正されていること。重要: 必ずファイル全量を出力し、既存ファイルとそのまま置換可能な形式にすること。",
        },
        "fix_moderate": {
            "source_code.md": "修正・改善されたソースコード。ロジックの変更や追加が反映されていること。重要: 必ずファイル全量を出力し、既存ファイルとそのまま置換可能な形式にすること。",
            "implementation_notes.md": "今回の修正に関する説明と、影響範囲についてのメモ。",
        },
        "fix_complex": {
            "source_code.md": "修正・改善されたソースコード。設計変更や大規模なリファクタリングが正しく行われていること。重要: 必ずファイル全量を出力し、既存ファイルとそのまま置換可能な形式にすること。",
            "architecture_updates.md": "今回の修正に伴う設計・アーキテクチャの変更点の説明。",
        },
    }
    
    def __init__(self, gemini: GeminiClient, max_turns: int = 12, min_turns: int = 4):
        """
        Args:
            gemini: GeminiClientインスタンス
            max_turns: 1フェーズあたりの最大ターン数
            min_turns: ゲートチェック発動前の最小ターン数
        """
        self.gemini = gemini
        self.max_turns = max_turns
        self.min_turns = min_turns
    
    def run_phase(
        self,
        phase_name: str,
        roles: dict,
        phase_goal: str,
        input_context: str,
        artifact_manager: ArtifactManager,
        dump_state_cb: callable = None,
    ) -> PhaseResult:
        """
        1フェーズを実行する。

        Args:
            phase_name: フェーズ名（"discovery", "design"）
            roles: setup_roles() の戻り値
            phase_goal: フェーズのゴール説明
            input_context: 入力コンテキスト（前フェーズ成果物等）
            artifact_manager: 成果物管理インスタンス
        Returns:
            PhaseResult: フェーズ実行結果
        """
        print(f"\n{'='*60}")
        print(f"⚔️  Phase: {phase_name.upper()} 開始")
        print(f"{'='*60}")
        
        history = []
        gate_passed = False
        turn = 0
        
        def _update_state(status_msg, current_speaker=None):
            if dump_state_cb:
                dump_state_cb(
                    phase_name=phase_name,
                    status=status_msg,
                    turn=turn,
                    max_turns=self.max_turns,
                    current_speaker=current_speaker,
                    history=history
                )
        
        _update_state("フェーズ開始")
        
        # --- ターンループ ---
        while turn < self.max_turns and not gate_passed:
            turn += 1
            print(f"\n--- Turn {turn}/{self.max_turns} ---")
            
            # 次の発言者を選出
            speaker_key = self._select_next_speaker(roles, history)
            
            if speaker_key is None:
                # 全員の意欲が低い場合、PMが介入
                speaker_key = "pm"
                print(f"  [*] 全員の発言意欲が低いため、PMが介入します")
            
            speaker = roles[speaker_key]
            print(f"  [>] {speaker['emoji']} {speaker['name']} が発言中...")
            
            # エージェントの発言を生成
            _update_state(f"{speaker['name']} が発言中...", current_speaker=speaker)
            message = self._agent_speak(
                speaker, phase_goal, input_context, history
            )
            
            history.append({
                "turn": turn,
                "speaker": speaker["name"],
                "speaker_key": speaker_key,
                "message": message,
            })
            
            # 発言の冒頭を表示
            preview = message[:100].replace('\n', ' ')
            print(f"  [<] {preview}...")
            
            # 最小ターン数を超えたらゲートチェック
            _update_state("待機中...", current_speaker=speaker)
            if turn >= self.min_turns and speaker_key == "pm":
                if self._check_gate_tag(message):
                    gate_passed = True
                    print(f"\n✅ ゲートチェック通過！ (Turn {turn})")
                    _update_state("ゲートチェック通過！")
            
            time.sleep(1)  # API負荷を抑える
        
        if not gate_passed and turn >= self.max_turns:
            print(f"\n⚠️  最大ターン数 ({self.max_turns}) 到達。強制的にゲートチェックを実施...")
            gate_passed = self._force_gate_check(phase_name, roles, history, input_context)
        
        # --- 成果物生成 ---
        artifacts = {}
        if gate_passed:
            _update_state("成果物を生成中...")
            artifacts = self._generate_artifacts(
                phase_name, history, input_context, artifact_manager
            )
            _update_state("フェーズ完了")
        
        return PhaseResult(
            phase_name=phase_name,
            gate_passed=gate_passed,
            artifacts=artifacts,
            log=history,
        )
    
    def _select_next_speaker(self, roles: dict, history: list) -> str:
        """
        自発性スコアに基づいて次の発言者を選出する。
        Discussion Engineの select_next_speaker と同等。
        """
        if not history:
            # 初ターンはPM以外からランダムに選出（PMは司会なので後から）
            non_pm = [k for k in roles if k != "pm"]
            return non_pm[0] if non_pm else "pm"
        
        # 直前の発言者は除外
        last_speaker = history[-1]["speaker_key"]
        candidates = {k: v for k, v in roles.items() if k != last_speaker}
        
        if not candidates:
            return list(roles.keys())[0]
        
        # 並列でeagerness評価
        recent_log = self._format_log(history, limit=5)
        scores = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as executor:
            futures = {}
            for role_key, role_info in candidates.items():
                prompt = EAGERNESS_PROMPT.format(
                    system_instruction=role_info["system_instruction"],
                    recent_log=recent_log,
                )
                futures[executor.submit(self.gemini.generate, prompt)] = role_key
            
            for future in concurrent.futures.as_completed(futures):
                role_key = futures[future]
                try:
                    response = future.result()
                    score = self._parse_eagerness(response)
                    scores.append({"name": role_key, "score": score})
                except Exception as e:
                    print(f"  [!] {role_key} のeagerness評価でエラー: {e}")
                    scores.append({"name": role_key, "score": 30})
        
        if not scores:
            return list(candidates.keys())[0]
        
        # 最高スコアのロールを選出
        best = max(scores, key=lambda x: x["score"])
        print(f"  [*] Eagerness: {', '.join(f'{s['name']}={s['score']}' for s in scores)} → {best['name']}")
        
        # 全員スコアが低い場合はNone（PMが介入）
        if best["score"] < 20:
            return None
        
        return best["name"]
    
    def _agent_speak(self, speaker: dict, phase_goal: str, input_context: str, history: list) -> str:
        """エージェントに発言を生成させる"""
        prompt = DISCUSSION_PROMPT.format(
            system_instruction=speaker["system_instruction"],
            phase_goal=phase_goal,
            input_context=input_context,
            full_log=self._format_log(history),
        )
        return self.gemini.generate(prompt)
    
    def _force_gate_check(self, phase_name: str, roles: dict, history: list, input_context: str) -> bool:
        """最大ターン到達時の強制ゲートチェック"""
        pm = roles.get("pm")
        if not pm:
            return True
        
        gate_criteria = self.GATE_CRITERIA.get(phase_name, "")
        prompt = GATE_CHECK_PROMPT.format(
            full_log=self._format_log(history),
            phase_name=phase_name,
            gate_criteria=gate_criteria,
        )
        
        response = self.gemini.generate(prompt, system_instruction=pm["system_instruction"])
        history.append({
            "turn": len(history) + 1,
            "speaker": pm["name"],
            "speaker_key": "pm",
            "message": response,
        })
        
        return self._check_gate_tag(response)
    
    def _generate_artifacts(
        self,
        phase_name: str,
        history: list,
        input_context: str,
        artifact_manager: ArtifactManager,
    ) -> dict:
        """フェーズの議論結果から成果物を生成する"""
        artifact_defs = self.PHASE_ARTIFACTS.get(phase_name, {})
        artifacts = {}
        
        print(f"\n📝 成果物生成中 ({len(artifact_defs)} 件)...")
        
        for filename, description in artifact_defs.items():
            print(f"  [*] {filename} を生成中...")
            prompt = ARTIFACT_PROMPT.format(
                artifact_name=filename,
                full_log=self._format_log(history),
                input_context=input_context,
                artifact_description=description,
            )
            
            content = self.gemini.generate(prompt)
            artifact_manager.save_artifact(phase_name, filename, content)
            artifacts[filename] = content
        
        return artifacts
    
    def _check_gate_tag(self, message: str) -> bool:
        """発言内の [GATE_PASSED: true] タグを検出する"""
        return bool(re.search(r'\[GATE_PASSED:\s*true\]', message, re.IGNORECASE))
    
    def _parse_eagerness(self, response: str) -> int:
        """応答テキストからeagernessスコアを抽出する"""
        match = re.search(r'\[Eagerness:\s*(\d+)\]', response)
        if match:
            return min(100, max(0, int(match.group(1))))
        # スコアが見つからない場合はデフォルト値
        return 50
    
    @staticmethod
    def _format_log(history: list, limit: int = None) -> str:
        """議論ログをフォーマットする"""
        entries = history[-limit:] if limit else history
        if not entries:
            return "(まだ議論は始まっていません)"
        
        lines = []
        for entry in entries:
            lines.append(f"【{entry['speaker']}】\n{entry['message']}\n")
        return "\n---\n".join(lines)
