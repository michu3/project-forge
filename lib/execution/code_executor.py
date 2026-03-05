"""
code_executor.py - セルフヒーリング実行エンジン（Phase 5: Execute）

生成されたソースコードを subprocess サンドボックスで実行し、
pytest によるテスト結果を構造化して返す。
テスト失敗時は Developer エージェントへエラー情報を渡して修正コードを再生成する
「セルフヒーリングループ」を実装する。

使用例:
    executor = CodeExecutor(gemini_client, project_dir)
    result = executor.run_with_healing(
        source_code_path=Path("artifacts/build/hello.py"),
        test_code_path=Path("artifacts/test/test_hello.py"),
        developer_instruction="...",
        max_retries=3,
    )
"""

import re
import sys
import time
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib.core.gemini_client import GeminiClient


# ========================
# データクラス
# ========================

@dataclass
class TestCaseResult:
    """1件のテストケースの結果"""
    name: str
    status: str          # "PASSED" | "FAILED" | "ERROR"
    duration_ms: float = 0.0
    error_message: str = ""


@dataclass
class ExecutionResult:
    """コード実行・テスト結果の全体サマリー"""
    all_passed: bool
    total: int
    passed: int
    failed: int
    errors: int
    duration_ms: float
    stdout: str
    stderr: str
    returncode: int
    test_cases: list[TestCaseResult] = field(default_factory=list)
    attempt: int = 1


@dataclass
class HealingResult:
    """セルフヒーリングループの最終結果"""
    success: bool
    attempts: int
    final_result: Optional[ExecutionResult]
    final_source_code: str       # 最後にテストが通ったor試みたコード
    final_test_code: str         # 最後にテストが通ったor試みたテストコード
    escalation_needed: bool = False
    escalation_reason: str = ""


# ========================
# プロンプト定義
# ========================

FIX_CODE_PROMPT = """\
あなたは優秀な Python デベロッパーです。
以下のコードを実行したところ、pytest でテストが失敗しました。

## 現在のソースコード
```python
{source_code}
```

## 現在のテストコード
```python
{test_code}
```

## テスト実行結果（試行 {attempt}/{max_retries}）
- 結果: {passed} PASS / {failed} FAIL / {errors} ERROR
- 実行時間: {duration_ms:.1f}ms

### 失敗したテスト
{failed_tests_detail}

### 標準エラー出力 (stderr)
```
{stderr}
```

## 修正依頼
上記のエラーを修正してください。
以下のフォーマットで **ソースコードのみ** を回答してください（テストコードは修正不要な場合は省略可）。

### 修正ソースコード
```python
<修正したソースコードをそのまま出力（コメントは日本語で）>
```

### 修正テストコード（変更が必要な場合のみ）
```python
<修正したテストコードをそのまま出力>
```

### 修正の根拠（1〜3文で）
<なぜその修正を行ったかを日本語で簡潔に説明>
"""


# ========================
# CodeExecutor クラス
# ========================

class CodeExecutor:
    """
    生成されたコードをサンドボックスで実行し、
    失敗時は AI エージェントによる自動修正ループを実行するクラス。

    サンドボックス方式: subprocess（タイムアウト制御付き）
    将来的に Docker 対応予定（strategy パターンで切り替え可能）
    """

    TIMEOUT_SECONDS = 30   # 1回のコード実行の最大秒数
    MAX_RETRIES = 3        # デフォルトの最大リトライ回数

    def __init__(self, gemini: GeminiClient, project_dir: Path):
        """
        Args:
            gemini:      GeminiClient インスタンス（コード修正に使用）
            project_dir: プロジェクトルートディレクトリ
        """
        self.gemini = gemini
        self.project_dir = Path(project_dir)
        self.sandbox_dir = self.project_dir / "sandbox"
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------
    # 公開メソッド
    # ------------------------------------------

    def run_with_healing(
        self,
        source_code: str,
        test_code: str,
        source_filename: str = "main.py",
        test_filename: str = "test_main.py",
        developer_instruction: str = "",
        max_retries: int = MAX_RETRIES,
    ) -> HealingResult:
        """
        セルフヒーリングループを実行する。

        1. sandbox/ にコードファイルを配置
        2. pytest で実行
        3. 失敗 → Developer エージェントに修正依頼 → 再試行（最大 max_retries 回）
        4. 成功 or max_retries 到達で終了

        Args:
            source_code:          ソースコードの文字列
            test_code:            テストコードの文字列
            source_filename:      ソースファイル名（sandbox/ 内に配置）
            test_filename:        テストファイル名（sandbox/ 内に配置）
            developer_instruction: Developer ロールのシステム指示
            max_retries:          最大リトライ回数
        Returns:
            HealingResult
        """
        current_source = source_code
        current_test = test_code

        print(f"\n{'='*60}")
        print(f"🔧 Phase 5: Execute（セルフヒーリング）開始")
        print(f"   最大試行回数: {max_retries}")
        print(f"{'='*60}")

        for attempt in range(1, max_retries + 1):
            print(f"\n--- 試行 {attempt}/{max_retries} ---")

            # sandbox へ書き込み
            self._write_to_sandbox(source_filename, current_source)
            self._write_to_sandbox(test_filename, current_test)

            # 実行
            result = self._run_pytest(test_filename, attempt)

            if result.all_passed:
                print(f"\n✅ 全テスト PASS！（試行 {attempt}）")
                # 成功したコードを成果物として保存
                self._save_healed_artifacts(
                    source_filename, current_source,
                    test_filename, current_test,
                )
                return HealingResult(
                    success=True,
                    attempts=attempt,
                    final_result=result,
                    final_source_code=current_source,
                    final_test_code=current_test,
                )

            # 失敗の場合
            print(f"  ❌ テスト失敗: {result.passed}PASS / {result.failed}FAIL / {result.errors}ERROR")
            self._log_failure(result, attempt)

            if attempt < max_retries:
                print(f"\n🔄 Developer エージェントがコードを修正中...")
                fixed = self._request_code_fix(
                    source_code=current_source,
                    test_code=current_test,
                    result=result,
                    attempt=attempt,
                    max_retries=max_retries,
                    developer_instruction=developer_instruction,
                )
                current_source = fixed.get("source_code", current_source)
                current_test = fixed.get("test_code", current_test)
                print(f"  📝 修正根拠: {fixed.get('rationale', '（説明なし）')}")
                time.sleep(1)

        # 全試行失敗 → エスカレーション
        print(f"\n⚠️  {max_retries} 回の試行が全て失敗。人間にエスカレーションします。")
        self._save_escalation_report(result, max_retries)

        return HealingResult(
            success=False,
            attempts=max_retries,
            final_result=result,
            final_source_code=current_source,
            final_test_code=current_test,
            escalation_needed=True,
            escalation_reason=f"{max_retries} 回の試行でテストが通過しませんでした。"
                              f"最終エラー: {result.stderr[:200]}",
        )

    def run_once(self, code: str, filename: str = "script.py") -> ExecutionResult:
        """
        コードをサンドボックスで単発実行する（テストなし）。
        フォールバックや動作確認に使用する。
        """
        self._write_to_sandbox(filename, code)
        return self._run_script(filename)

    # ------------------------------------------
    # サンドボックス内実行
    # ------------------------------------------

    def _run_pytest(self, test_filename: str, attempt: int = 1) -> ExecutionResult:
        """pytest を sandbox/ 内で実行し、結果を構造化して返す"""
        start = time.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_filename, "-v", "--tb=short", "--no-header"],
                cwd=str(self.sandbox_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace", # Windows環境でのエンコーディング不一致対策
                timeout=self.TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                all_passed=False,
                total=0, passed=0, failed=0, errors=1,
                duration_ms=elapsed,
                stdout="",
                stderr=f"タイムアウト（{self.TIMEOUT_SECONDS}秒）",
                returncode=-1,
                attempt=attempt,
            )

        elapsed = (time.perf_counter() - start) * 1000
        return self._parse_pytest_output(result, elapsed, attempt)

    def _run_script(self, filename: str) -> ExecutionResult:
        """Python スクリプトを直接実行する"""
        start = time.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, filename],
                cwd=str(self.sandbox_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                all_passed=False,
                total=0, passed=0, failed=0, errors=1,
                duration_ms=elapsed,
                stdout="",
                stderr=f"タイムアウト（{self.TIMEOUT_SECONDS}秒）",
                returncode=-1,
            )

        elapsed = (time.perf_counter() - start) * 1000
        success = result.returncode == 0
        return ExecutionResult(
            all_passed=success,
            total=1,
            passed=1 if success else 0,
            failed=0 if success else 1,
            errors=0,
            duration_ms=elapsed,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    # ------------------------------------------
    # AI コード修正
    # ------------------------------------------

    def _request_code_fix(
        self,
        source_code: str,
        test_code: str,
        result: ExecutionResult,
        attempt: int,
        max_retries: int,
        developer_instruction: str,
    ) -> dict:
        """
        Developer エージェントに修正コードの生成を依頼する。

        Returns:
            dict: {"source_code": str, "test_code": str, "rationale": str}
        """
        # 失敗したテストの詳細を整形
        failed_detail_lines = []
        for tc in result.test_cases:
            if tc.status in ("FAILED", "ERROR"):
                failed_detail_lines.append(f"- **{tc.name}** ({tc.status})")
                if tc.error_message:
                    failed_detail_lines.append(f"  ```\n  {tc.error_message[:300]}\n  ```")

        if not failed_detail_lines:
            failed_detail_lines = [f"（pytest の stdout から詳細抽出）\n```\n{result.stdout[-500:]}\n```"]

        prompt = FIX_CODE_PROMPT.format(
            source_code=source_code,
            test_code=test_code,
            attempt=attempt,
            max_retries=max_retries,
            passed=result.passed,
            failed=result.failed,
            errors=result.errors,
            duration_ms=result.duration_ms,
            failed_tests_detail="\n".join(failed_detail_lines),
            stderr=result.stderr[:500],
        )

        response = self.gemini.generate(
            prompt,
            system_instruction=developer_instruction or None,
        )

        return self._parse_fix_response(response, source_code, test_code)

    def _parse_fix_response(self, response: str, original_source: str, original_test: str) -> dict:
        """
        AI の応答から修正されたソースコードとテストコードを抽出する。
        """
        result = {
            "source_code": original_source,
            "test_code": original_test,
            "rationale": "",
        }

        # コードブロックを全て抽出
        code_blocks = re.findall(r'```python\s*\n(.*?)\n```', response, re.DOTALL)

        if len(code_blocks) >= 1:
            result["source_code"] = code_blocks[0].strip()
        if len(code_blocks) >= 2:
            result["test_code"] = code_blocks[1].strip()

        # 修正根拠の抽出
        rationale_match = re.search(r'###\s*修正の根拠[^\n]*\n(.*?)(?=###|\Z)', response, re.DOTALL)
        if rationale_match:
            result["rationale"] = rationale_match.group(1).strip()[:200]

        return result

    # ------------------------------------------
    # ユーティリティ
    # ------------------------------------------

    def _write_to_sandbox(self, filename: str, content: str):
        """sandbox/ ディレクトリにファイルを書き込む"""
        filepath = self.sandbox_dir / filename
        filepath.write_text(content, encoding="utf-8")

    def _parse_pytest_output(
        self, proc_result, elapsed_ms: float, attempt: int
    ) -> ExecutionResult:
        """pytest の stdout/stderr を解析して ExecutionResult を返す"""
        stdout = proc_result.stdout or ""
        stderr = proc_result.stderr or ""

        # サマリー行のパース（例: "2 passed, 1 failed in 0.12s"）
        summary_match = re.search(
            r'(\d+) passed(?:,\s*(\d+) failed)?(?:,\s*(\d+) error)?',
            stdout,
        )
        passed = int(summary_match.group(1)) if summary_match else 0
        failed = int(summary_match.group(2) or 0) if summary_match else 0
        errors = int(summary_match.group(3) or 0) if summary_match else 0
        total = passed + failed + errors

        # 失敗なしで pytest が 0 を返せば成功
        # returncode が 0 でも passed が取れない場合は "no tests" なので成功扱い
        all_passed = proc_result.returncode == 0

        # 各テストケースの結果を抽出（PASSED / FAILED / ERROR の行）
        test_cases = []
        for line in stdout.splitlines():
            m = re.match(r'^(.*)\s+(PASSED|FAILED|ERROR)\s*$', line.strip())
            if m:
                test_cases.append(TestCaseResult(
                    name=m.group(1).strip(),
                    status=m.group(2),
                ))

        # FAILED の場合、エラーメッセージを切り出す（簡易）
        failed_blocks = re.findall(r'FAILED (.*?) - (.*?)(?=\nFAILED|\Z)', stdout, re.DOTALL)
        for tc_name, tc_err in failed_blocks:
            for tc in test_cases:
                if tc_name.strip() in tc.name:
                    tc.error_message = tc_err.strip()[:300]

        return ExecutionResult(
            all_passed=all_passed,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            duration_ms=elapsed_ms,
            stdout=stdout,
            stderr=stderr,
            returncode=proc_result.returncode,
            test_cases=test_cases,
            attempt=attempt,
        )

    def _save_healed_artifacts(
        self,
        source_filename: str, source_code: str,
        test_filename: str, test_code: str,
    ):
        """セルフヒーリング後の最終コードを artifacts/execute/ に保存する"""
        execute_dir = self.project_dir / "artifacts" / "execute"
        execute_dir.mkdir(parents=True, exist_ok=True)
        (execute_dir / source_filename).write_text(source_code, encoding="utf-8")
        (execute_dir / test_filename).write_text(test_code, encoding="utf-8")
        print(f"\n  [+] 最終コードを artifacts/execute/ に保存しました")

    def _save_escalation_report(self, result: ExecutionResult, attempts: int):
        """エスカレーション時のレポートを保存する"""
        report_dir = self.project_dir / "artifacts" / "execute"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "escalation_report.md"

        report_lines = [
            "# ⚠️ セルフヒーリング エスカレーションレポート",
            "",
            f"**試行回数**: {attempts}",
            f"**最終テスト結果**: {result.passed}PASS / {result.failed}FAIL / {result.errors}ERROR",
            "",
            "## 最終 stderr",
            "```",
            result.stderr[:1000],
            "```",
            "",
            "## 最終 stdout",
            "```",
            result.stdout[:1000],
            "```",
            "",
            "## 次のアクション",
            "- [ ] 人間による手動修正が必要です。",
            "- [ ] `sandbox/` 内のファイルを直接確認してください。",
        ]

        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        print(f"  [+] エスカレーションレポートを保存: {report_path}")

    def _log_failure(self, result: ExecutionResult, attempt: int):
        """失敗の詳細をコンソールに出力する"""
        if result.test_cases:
            for tc in result.test_cases:
                status_icon = "✅" if tc.status == "PASSED" else "❌"
                print(f"    {status_icon} {tc.name} [{tc.status}]")
                if tc.error_message:
                    truncated = tc.error_message[:150].replace("\n", " ")
                    print(f"       └─ {truncated}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:200]}")


# ========================
# CLI エントリポイント（単体テスト用）
# ========================

if __name__ == "__main__":
    """
    単体テスト用CLIエントリポイント。
    指定したソースコードとテストコードに対してセルフヒーリングを実行する。

    使用例:
        python -m lib.code_executor <source.py> <test_file.py>
    """
    import sys as _sys
    from pathlib import Path as _Path

    if len(_sys.argv) < 3:
        print("Usage: python -m lib.code_executor <source.py> <test_file.py>")
        _sys.exit(1)

    source_path = _Path(_sys.argv[1])
    test_path = _Path(_sys.argv[2])

    if not source_path.exists() or not test_path.exists():
        print(f"Error: ファイルが見つかりません")
        _sys.exit(1)

    from .gemini_client import GeminiClient as _GC
    gemini = _GC(mock_mode=True)

    executor = CodeExecutor(gemini, _Path("."))
    healing = executor.run_with_healing(
        source_code=source_path.read_text(encoding="utf-8"),
        test_code=test_path.read_text(encoding="utf-8"),
        source_filename=source_path.name,
        test_filename=test_path.name,
    )

    print(f"\n{'='*60}")
    if healing.success:
        print(f"✅ セルフヒーリング成功（{healing.attempts} 試行）")
    else:
        print(f"❌ セルフヒーリング失敗（{healing.attempts} 試行）")
        print(f"   エスカレーション: {healing.escalation_reason}")
