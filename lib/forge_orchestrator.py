"""
forge_orchestrator.py - Project Forgeメインオーケストレーター

案件テキスト（brief）を受け取り、Phase 1（深掘り）→ Phase 4（テスト）まで
を順次実行する統合エントリポイント。

使い方:
    python -m lib.forge_orchestrator "案件テキスト"          # 通常実行
    python -m lib.forge_orchestrator "案件テキスト" --mock   # モックモード
    python -m lib.forge_orchestrator "案件テキスト" --pr     # GitHub PR 自動作成
    python -m lib.forge_orchestrator --resume projects/DIR  # 既存プロジェクトから再開
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime

from .role_generator import setup_roles, get_phase_participants
from .phase_engine import PhaseEngine, PhaseResult
from .artifact_manager import ArtifactManager
from .gemini_client import GeminiClient

BASE_DIR = Path(__file__).parent.parent.absolute()
PROJECTS_DIR = BASE_DIR / "projects"
TEMPLATES_DIR = BASE_DIR / "templates"

# .env ファイルの環境変数を読み込む
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

# 実装フェーズの定義（Phase 1-4）
PHASES = [
    {
        "name": "discovery",
        "display_name": "🔍 Phase 1: 深掘り（Discovery）",
        "goal": "案件概要から具体的で実装可能な要件を明確化し、プロジェクトのスコープとリスクを定義する。",
    },
    {
        "name": "design",
        "display_name": "📐 Phase 2: 設計（Design）",
        "goal": "Phase 1で確定した要件に基づき、システムのアーキテクチャを設計し、テスト戦略を策定する。",
    },
    {
        "name": "build",
        "display_name": "⚒️ Phase 3: 実装（Build）",
        "goal": "設計書に基づき、システムのコアとなるソースコードおよび構成ファイルの詳細な実装案を提示する。",
    },
    {
        "name": "test",
        "display_name": "🧪 Phase 4: テスト（Test）",
        "goal": "実装コードに対してテスト戦略に基づくテストコードや評価スクリプトを作成し、検証計画を確実なものにする。",
    },
]


def setup_project(brief: str) -> Path:
    """
    プロジェクトのセッションディレクトリを作成し、briefを保存する。

    Args:
        brief: 案件概要テキスト
    Returns:
        Path: プロジェクトディレクトリのパス
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # briefの最初の20文字をディレクトリ名に使用（安全な文字のみ）
    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in brief[:20]).strip("_")
    project_name = f"{timestamp}_{safe_name}"
    
    project_dir = PROJECTS_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # brief.md を保存
    brief_path = project_dir / "brief.md"
    brief_path.write_text(f"# 案件概要\n\n{brief}\n", encoding='utf-8')
    
    print(f"[+] プロジェクトディレクトリ作成: {project_dir}")
    return project_dir


def run_project(brief: str = None, mock_mode: bool = False, run_execute: bool = False, resume_dir: str = None) -> dict:
    """
    プロジェクト全体を実行する（Phase 1-4, オプションで Phase 5）。

    Args:
        brief:       案件概要テキスト
        mock_mode:   Trueの場合、Gemini APIを呼ばずモック応答で実行
        run_execute: Trueの場合、Phase 5（セルフヒーリング）を実行
        resume_dir:  既存のプロジェクトディレクトリ（再開用）
    Returns:
        dict: 実行結果
    """
    print("=" * 60)
    print("⚒️  Project Forge - AI SIベンダーシステム")
    print("=" * 60)
    print(f"案件: {brief}")
    print(f"実行フェーズ: {len(PHASES)} フェーズ (1:深掘り -> 2:設計 -> 3:実装 -> 4:テスト)")
    print("=" * 60)
    
    # 1. プロジェクトセットアップ
    if resume_dir:
        project_dir = Path(resume_dir).absolute()
        if not project_dir.exists():
            raise FileNotFoundError(f"Resume directory not found: {project_dir}")
        
        # brief.md から内容を復元（あれば）
        brief_path = project_dir / "brief.md"
        if brief_path.exists():
            brief = brief_path.read_text(encoding='utf-8')
        else:
            brief = "Resumed project (brief not found)"
    else:
        project_dir = setup_project(brief)

    artifact_manager = ArtifactManager(project_dir)
    gemini = GeminiClient(mock_mode=mock_mode)
    engine = PhaseEngine(gemini)
    
    results = []
    all_passed = True
    
    # 2. フェーズ順次実行
    for phase_def in PHASES:
        phase_name = phase_def["name"]
        
        print(f"\n{'='*60}")
        print(f"{phase_def['display_name']}")
        print(f"{'='*60}")
        
        # 2a. このフェーズの成果物がすべて存在するか確認
        if resume_dir:
            artifact_defs = engine.PHASE_ARTIFACTS.get(phase_name, {})
            all_exists = True
            for filename in artifact_defs:
                if not (project_dir / "artifacts" / phase_name / filename).exists():
                    all_exists = False
                    break
            
            if all_exists:
                print(f"  [*] {phase_name} の成果物が既に存在するためスキップします。")
                results.append({"phase": phase_name, "success": True, "skipped": True})
                continue

        # 2b. このフェーズの参加ロールをセットアップ
        agents_dir = project_dir / "agents" / phase_name
        roles = setup_roles(agents_dir, brief, phase_name, TEMPLATES_DIR)
        
        # 2b. 入力コンテキストの取得
        input_context = artifact_manager.get_input_context(phase_name)
        
        # 状態保存コールバックの定義
        def dump_state_cb(phase_name, status, turn, max_turns, current_speaker, history):
            state = {
                "project_brief": brief,
                "current_phase": phase_name,
                "status": status,
                "turn": turn,
                "max_turns": max_turns,
                "current_speaker": current_speaker,
                "history": history,
                "roles": {k: {"name": v["name"], "emoji": v["emoji"]} for k, v in roles.items()},
                "last_updated": datetime.now().isoformat()
            }
            state_path = project_dir / "state.json"
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            # 汎用的に最新状態を監視できるようにシンボリックリンク的なコピーも作成
            latest_path = PROJECTS_DIR / "latest_state.json"
            latest_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

        # 2c. フェーズ実行
        result = engine.run_phase(
            phase_name=phase_name,
            roles=roles,
            phase_goal=phase_def["goal"],
            input_context=input_context,
            artifact_manager=artifact_manager,
            dump_state_cb=dump_state_cb,
        )
        
        results.append(result)
        
        # 2d. ログ保存
        log_path = project_dir / f"log_{phase_name}.json"
        log_path.write_text(
            json.dumps(result.log, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        # 2e. ゲート通過チェック
        if not result.gate_passed:
            print(f"\n❌ {phase_def['display_name']} のゲートチェックが不通過。")
            print("   差戻しが必要です。プロジェクトを一時停止します。")
            all_passed = False
            break
        
        print(f"\n✅ {phase_def['display_name']} 完了！")
    
    # 4. Phase 5: Execute（--execute フラグ時のみ）
    heal_result = None
    if run_execute and all_passed:
        heal_result = _run_execute_phase(project_dir, gemini, results)
        if heal_result and not heal_result.success:
            print("\n⚠️  Phase 5 セルフヒーリングが収束しませんでした。エスカレーションレポートを確認してください。")

    # 5. 最終レポート生成
    _generate_final_report(project_dir, brief, results, heal_result)

    # 6. プロジェクト成果物の物理展開（全フェーズ成功時のみ）
    if all_passed:
        _deploy_project_files(project_dir, artifact_manager)

    # 7. README.md 自動生成（全フェーズ成功時のみ）
    if all_passed:
        _generate_readme(project_dir, brief, gemini, artifact_manager)

    print(f"\n{'='*60}")
    if all_passed:
        if heal_result:
            icon = "✅" if heal_result.success else "⚠️ "
            print(f"🏯 プロジェクト完了！ {icon} Phase 5 (Execute): {'成功' if heal_result.success else 'エスカレーション'}")
        else:
            print("🏯 プロジェクト完了！ 全フェーズのゲートを通過しました。")
    else:
        print("⚠️  プロジェクト一時停止。差戻しフェーズがあります。")
    print(f"   成果物: {project_dir / 'artifacts'}")
    print(f"{'='*60}")
    
    final_results = []
    for r in results:
        if isinstance(r, dict):
            final_results.append({
                "phase": r.get("phase", "unknown"),
                "gate_passed": r.get("success", True),
                "artifacts": [],  # resume時はartifact_managerで管理
                "turns": 0,
                "skipped": True
            })
        else:
            final_results.append({
                "phase": r.phase_name,
                "gate_passed": r.gate_passed,
                "artifacts": list(r.artifacts.keys()),
                "turns": len(r.log),
                "skipped": False
            })

    return {
        "project_dir": str(project_dir),
        "results": final_results,
        "success": all_passed,
        "execute": {
            "ran": heal_result is not None,
            "success": heal_result.success if heal_result else None,
            "attempts": heal_result.attempts if heal_result else 0,
            "escalation_needed": heal_result.escalation_needed if heal_result else False,
        },
        "brief": brief,
    }

def _run_execute_phase(
    project_dir: Path,
    gemini: GeminiClient,
    phase_results: list,
    max_retries: int = 3,
):
    """
    Phase 5: Execute — セルフヒーリングループを実行する。

    Buildフェーズの source_code.md と Testフェーズの test_scripts.md
    から実際の Python コードを抽出して実行・検証する。
    """
    from .code_executor import CodeExecutor

    print(f"\n{'='*60}")
    print("\U0001f527 Phase 5: Execute 開始")
    print(f"{'='*60}")

    # --------------------------------
    # 1. Build成果物からソースコードを抽出
    # --------------------------------
    source_artifact = project_dir / "artifacts" / "build" / "source_code.md"
    if not source_artifact.exists():
        print("  [⚠️] source_code.md が見つかりません。Phase 5 をスキップします。")
        return None

    source_md = source_artifact.read_text(encoding="utf-8")
    source_code = _extract_python_code(source_md)

    if not source_code:
        print("  [⚠️] source_code.md から Python コードブロックを抽出できませんでした。")
        return None

    # --------------------------------
    # 2. Test成果物からテストコードを抽出
    # --------------------------------
    test_artifact = project_dir / "artifacts" / "test" / "test_scripts.md"
    if not test_artifact.exists():
        print("  [⚠️] test_scripts.md が見つかりません。Phase 5 をスキップします。")
        return None

    test_md = test_artifact.read_text(encoding="utf-8")
    test_code = _extract_python_code(test_md)

    if not test_code:
        print("  [⚠️] test_scripts.md から Python コードブロックを抽出できませんでした。")
        return None

    print(f"  [✓] ソースコード: {len(source_code)} chars")
    print(f"  [✓] テストコード: {len(test_code)} chars")

    # --------------------------------
    # 3. Developer ロールの指示を取得
    # --------------------------------
    developer_instruction = ""
    agent_dir = project_dir / "agents" / "build" / "developer"
    instruction_file = agent_dir / "INSTRUCTIONS.md"
    if instruction_file.exists():
        developer_instruction = instruction_file.read_text(encoding="utf-8")

    # --------------------------------
    # 4. CodeExecutor でセルフヒーリング実行
    # --------------------------------
    executor = CodeExecutor(gemini, project_dir)
    healing = executor.run_with_healing(
        source_code=source_code,
        test_code=test_code,
        source_filename="main.py",
        test_filename="test_main.py",
        developer_instruction=developer_instruction,
        max_retries=max_retries,
    )

    return healing


def _extract_python_code(markdown_text: str) -> str:
    """
    Markdown テキスト内のコードブロックを抽出する。
    最も柔軟なパターンで抽出を試みる。
    """
    import re
    # 全てのコードブロックを抽出
    blocks = re.findall(r'```(?:python|bash|text)?\s*(.*?)\n```', markdown_text, re.DOTALL | re.IGNORECASE)
    
    if not blocks:
        return ""
        
    # main.py という記述の直後にあるブロックを優先
    for i, block in enumerate(blocks):
        # ブロックの前のテキストを確認
        start_idx = markdown_text.find(block)
        prefix = markdown_text[max(0, start_idx-100):start_idx].lower()
        if 'main.py' in prefix:
            return block.strip()
            
    # 次に python っぽいものを優先
    for block in blocks:
        if 'import ' in block or 'def ' in block or 'class ' in block:
            return block.strip()
            
    return blocks[0].strip()


def _generate_final_report(project_dir: Path, brief: str, results: list, heal_result=None):
    """プロジェクト最終レポートを生成する"""
    report_lines = [
        f"# Project Forge 実行レポート",
        f"",
        f"**案件**: {brief}",
        f"**実行日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## フェーズ実行結果",
        f"",
    ]
    
    for result in results:
        # resume 時は dict, 通常実行時は PhaseResult オブジェクト
        if isinstance(result, dict):
            p_name = result.get("phase", "unknown")
            is_passed = result.get("success", False)
            p_log = []
            p_artifacts = []
        else:
            p_name = result.phase_name
            is_passed = result.gate_passed
            p_log = result.log
            p_artifacts = list(result.artifacts.keys()) if result.artifacts else []

        status = "✅ 通過" if is_passed else "❌ 不通過"
        report_lines.append(f"### {p_name.capitalize()}")
        report_lines.append(f"- ゲート: {status}")
        if not isinstance(result, dict) or not result.get("skipped"):
            report_lines.append(f"- ターン数: {len(p_log)}")
            report_lines.append(f"- 成果物: {', '.join(p_artifacts) if p_artifacts else 'なし'}")
        else:
            report_lines.append("- 状態: 既存の成果物があるためスキップされました")
        report_lines.append("")
        
        # 議論ログの要約
        if p_log:
            report_lines.append("#### 議論ログ（要約）")
            for entry in p_log:
                preview = entry['message'][:150].replace('\n', ' ')
                report_lines.append(f"> **{entry['speaker']}** (Turn {entry['turn']}): {preview}...")
                report_lines.append(">")
            report_lines.append("")
    
    # Phase 5 結果をレポートに追記
    if heal_result is not None:
        report_lines.append("## Phase 5: Execute（セルフヒーリング）")
        if heal_result.success:
            report_lines.append(f"- **結果**: ✅ SUCCESS（{heal_result.attempts} 試行で全テスト PASS）")
        else:
            report_lines.append(f"- **結果**: ❌ ESCALATION（{heal_result.attempts} 試行でも収束せず）")
            report_lines.append(f"- **理由**: {heal_result.escalation_reason}")
        report_lines.append("")
    
    report_path = project_dir / "FINAL_REPORT.md"
    report_path.write_text("\n".join(report_lines), encoding='utf-8')
    print(f"[+] 最終レポート: {report_path}")


def _generate_readme(
    project_dir: Path,
    brief: str,
    gemini: GeminiClient,
    artifact_manager: 'ArtifactManager',
):
    """
    全フェーズの成果物を要約し、プロジェクトのREADME.mdを自動生成する。

    Gemini を使って全成果物を読み込み、プロジェクトの概要、構成、
    セットアップ手順、使い方をまとめた README.md を生成する。

    Args:
        project_dir: プロジェクトルートディレクトリ
        brief: 案件概要テキスト
        gemini: GeminiClientインスタンス
        artifact_manager: ArtifactManagerインスタンス
    """
    print("\n📝 README.md を生成中...")

    # 全フェーズの成果物を収集
    all_artifacts_text = ""
    for phase_name in ["discovery", "design", "build", "test"]:
        artifacts = artifact_manager.load_phase_artifacts(phase_name)
        if artifacts:
            all_artifacts_text += f"\n## {phase_name.upper()} フェーズの成果物\n\n"
            for filename, content in artifacts.items():
                # 各成果物の冒頭 1500 文字を取得（トークン制限対策）
                truncated = content[:1500]
                all_artifacts_text += f"### {filename}\n{truncated}\n\n"

    readme_prompt = f"""以下のプロジェクト情報を元に、GitHub リポジトリのルートに配置する
README.md を日本語で作成してください。

## 案件概要
{brief}

## 成果物サマリー
{all_artifacts_text}

---
以下のセクションを含めてください:
1. プロジェクト名とバッジ（概要を1行で）
2. 概要（このシステムが何をするか、2-3文で）
3. 主要機能（箇条書き）
4. システム構成（ディレクトリ構造）
5. セットアップ手順（前提条件、.env設定、依存ライブラリ）
6. 使い方（実行コマンド例）
7. テスト方法
8. ドキュメント一覧（各フェーズの成果物へのリンク）
9. ライセンス（MIT）

Markdown フォーマットで出力してください。不要な前書きや説明は不要です。
README.md の内容のみを出力してください。"""

    try:
        readme_content = gemini.generate(readme_prompt)
        readme_path = project_dir / "README.md"
        readme_path.write_text(readme_content, encoding='utf-8')
        print(f"  [+] README.md 生成完了: {readme_path}")
    except Exception as e:
        # README 生成失敗はプロジェクト全体を停止させない
        print(f"  [⚠️] README.md 生成に失敗しました（プロジェクトへの影響なし）: {e}")


def _deploy_project_files(project_dir: Path, artifact_manager: 'ArtifactManager'):
    """
    source_code.md を解析し、設計通りのディレクトリ構造でファイルを物理展開する。
    """
    print("\n📦 プロジェクトファイルを展開中...")
    
    source_md = artifact_manager.load_artifact("build", "source_code.md")
    if not source_md:
        print("  [⚠️] source_code.md が見つからないため展開をスキップします。")
        return

    import re
    # セクションごとに分割 (### で始まる行)
    sections = re.split(r'\n###\s+', '\n' + source_md)
    
    deployed_count = 0
    for section in sections:
        if not section.strip():
            continue
            
        # 1行目からファイル名を抽出
        lines = section.strip().split('\n')
        header = lines[0]
        
        # ファイル名と思われるパターンを検索 ([パス]/[名前].[拡張子])
        name_match = re.search(r'([a-zA-Z0-9_\-\./]+\.[a-z]+)', header)
        if not name_match:
            continue
            
        rel_path_str = name_match.group(1)
        
        # コードブロックを抽出
        code_match = re.search(r'```(?:[a-z]+)?\s*\n(.*?)\n```', section, re.DOTALL)
        if not code_match:
            continue
            
        content = code_match.group(1).strip()
        rel_path = Path(rel_path_str.strip())
        
        # 安全チェック
        if ".." in rel_path_str or rel_path.is_absolute():
            continue
            
        full_path = project_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')
        print(f"  [+] {rel_path} を展開しました")
        deployed_count += 1

    if deployed_count == 0:
        print("  [⚠️] ファイルが抽出できませんでした。単一ファイルとして展開を試みます。")
        code = _extract_python_code(source_md)
        if code:
            (project_dir / "main.py").write_text(code, encoding='utf-8')
            print(f"  [+] main.py を展開しました")
            deployed_count = 1
    
    print(f"✅ {deployed_count} 個のファイルを展開完了")


# --- CLI エントリポイント ---
if __name__ == "__main__":
    args = sys.argv[1:]
    brief_text = None
    resume_path = None
    
    # --resume オプションのパース
    if "--resume" in args:
        idx = args.index("--resume")
        if idx + 1 < len(args):
            resume_path = args[idx + 1]
            # brief_text は省略される可能性がある
        else:
            print("Error: --resume option requires a directory path.")
            sys.exit(1)
    elif args and not args[0].startswith("--"):
        brief_text = args[0]
    
    if not brief_text and not resume_path:
        print("Usage: python -m lib.forge_orchestrator \"案件概要テキスト\"")
        print("   or: python -m lib.forge_orchestrator --resume projects/DIR")
        sys.exit(1)

    mock = "--mock" in args
    create_pr = "--pr" in args
    run_execute = "--execute" in args
    
    outcome = run_project(brief_text, mock_mode=mock, run_execute=run_execute, resume_dir=resume_path)
    
    # --pr オプション: 全フェーズ成功 & 環境変数あり の場合のみ実行
    if create_pr and outcome.get("success"):
        github_token = os.environ.get("GITHUB_TOKEN")
        github_user = os.environ.get("GITHUB_USER")
        
        if not github_token or not github_user:
            print("\n⚠️  --pr オプションに必要な環境変数が設定されていません:")
            print("   export GITHUB_TOKEN=\"ghp_xxx...\"")
            print("   export GITHUB_USER=\"your-github-username\"")
            sys.exit(1)
        
        from .cicd_manager import CICDManager
        from .gemini_client import GeminiClient
        
        manager = CICDManager(
            github_user=github_user,
            token=github_token,
            gemini_client=GeminiClient(mock_mode=mock)
        )
        
        cicd_result = manager.create_pr_from_project(
            project_dir=Path(outcome["project_dir"]),
            brief=outcome.get("brief") or brief_text or "Resumed Project",
            phase_results=outcome["results"],
        )
        
        if cicd_result.success:
            print(f"\n🔗 PR URL: {cicd_result.pr_url}")
        else:
            print(f"\n❌ PR 作成失敗: {cicd_result.error}")
            sys.exit(1)
    elif create_pr and not outcome.get("success"):
        print("\n⚠️  全フェーズが完了していないため PR 作成をスキップします。")
