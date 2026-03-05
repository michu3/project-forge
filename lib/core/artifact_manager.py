"""
artifact_manager.py - フェーズ間成果物の管理モジュール

各フェーズが生成する成果物（要件定義書、設計書など）の
保存・読込・フェーズ間受渡しを管理する。
"""

import json
from pathlib import Path
from datetime import datetime


class ArtifactManager:
    """
    プロジェクト成果物のライフサイクルを管理するクラス。
    
    ディレクトリ構成:
        project_dir/
        └── artifacts/
            ├── discovery/
            │   ├── requirements.md
            │   └── risks.md
            ├── design/
            │   ├── architecture.md
            │   └── test_strategy.md
            └── manifest.json  # 成果物メタデータ
    """
    
    def __init__(self, project_dir: Path):
        """
        Args:
            project_dir: プロジェクトルートディレクトリ
        """
        self.project_dir = Path(project_dir)
        self.artifacts_dir = self.project_dir / "artifacts"
        self.manifest_path = self.artifacts_dir / "manifest.json"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._manifest = self._load_manifest()
    
    def save_artifact(self, phase_name: str, filename: str, content: str) -> Path:
        """
        フェーズ成果物を保存する。

        Args:
            phase_name: フェーズ名（"discovery", "design"等）
            filename: ファイル名（"requirements.md"等）
            content: 成果物の内容テキスト
        Returns:
            Path: 保存先のファイルパス
        """
        phase_dir = self.artifacts_dir / phase_name
        phase_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = phase_dir / filename
        filepath.write_text(content, encoding='utf-8')
        
        # マニフェスト更新
        self._update_manifest(phase_name, filename, filepath)
        
        print(f"  [+] 成果物保存: {phase_name}/{filename}")
        return filepath
    
    def load_artifact(self, phase_name: str, filename: str) -> str:
        """
        フェーズ成果物を読み込む。

        Args:
            phase_name: フェーズ名
            filename: ファイル名
        Returns:
            str: 成果物の内容テキスト
        Raises:
            FileNotFoundError: 指定された成果物が存在しない場合
        """
        filepath = self.artifacts_dir / phase_name / filename
        if not filepath.exists():
            raise FileNotFoundError(f"成果物が見つかりません: {phase_name}/{filename}")
        return filepath.read_text(encoding='utf-8')
    
    def load_phase_artifacts(self, phase_name: str) -> dict:
        """
        指定フェーズの全成果物を辞書で返す。

        Args:
            phase_name: フェーズ名
        Returns:
            dict: {ファイル名: 内容テキスト}
        """
        phase_dir = self.artifacts_dir / phase_name
        if not phase_dir.exists():
            return {}
        
        artifacts = {}
        for filepath in phase_dir.iterdir():
            if filepath.is_file() and filepath.suffix == '.md':
                artifacts[filepath.name] = filepath.read_text(encoding='utf-8')
        return artifacts
    
    def get_input_context(self, phase_name: str) -> str:
        """
        指定フェーズの入力コンテキスト（前フェーズの成果物）をフォーマットして返す。
        
        フェーズの依存関係:
            discovery → brief.md（プロジェクトルートから）
            design → discoveryの成果物
            build → designの成果物
            test → buildの成果物

        Args:
            phase_name: 現在のフェーズ名
        Returns:
            str: フォーマットされた入力コンテキスト
        """
        input_map = {
            "discovery": self._get_brief,
            "design": lambda: self._get_previous_phase("discovery"),
            "build": lambda: self._get_previous_phase("design"),
            "test": lambda: self._get_previous_phase("build"),
        }
        
        getter = input_map.get(phase_name)
        if getter is None:
            return ""
        return getter()
    
    def list_artifacts(self) -> dict:
        """全成果物の一覧をフェーズごとに返す"""
        result = {}
        for phase_dir in sorted(self.artifacts_dir.iterdir()):
            if phase_dir.is_dir():
                files = [f.name for f in phase_dir.iterdir() if f.is_file() and f.suffix == '.md']
                if files:
                    result[phase_dir.name] = files
        return result
    
    def _get_brief(self) -> str:
        """プロジェクトのbrief.mdを読み込む"""
        brief_path = self.project_dir / "brief.md"
        if brief_path.exists():
            content = brief_path.read_text(encoding='utf-8')
            return f"## 案件概要 (brief.md)\n\n{content}"
        return "案件概要が見つかりません。"
    
    def _get_previous_phase(self, prev_phase: str) -> str:
        """前フェーズの成果物をフォーマットして返す"""
        artifacts = self.load_phase_artifacts(prev_phase)
        if not artifacts:
            return f"前フェーズ ({prev_phase}) の成果物が見つかりません。"
        
        context_parts = [f"## 前フェーズ ({prev_phase}) の成果物\n"]
        for filename, content in artifacts.items():
            context_parts.append(f"### {filename}\n\n{content}\n")
        return "\n---\n".join(context_parts)
    
    def _update_manifest(self, phase_name: str, filename: str, filepath: Path):
        """マニフェストにメタデータを記録"""
        key = f"{phase_name}/{filename}"
        self._manifest[key] = {
            "phase": phase_name,
            "filename": filename,
            "path": str(filepath),
            "created_at": datetime.now().isoformat(),
        }
        self._save_manifest()
    
    def _load_manifest(self) -> dict:
        """マニフェストファイルを読み込む"""
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding='utf-8'))
        return {}
    
    def _save_manifest(self):
        """マニフェストファイルを保存する"""
        self.manifest_path.write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
