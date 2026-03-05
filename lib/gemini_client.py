"""
gemini_client.py - Gemini CLI呼出しラッパー

Discussion Engineの gemini_wrapper.py をベースに、Project Forge用に改善。
主な改善点:
  - クラスベースの設計（将来のSDK移行を容易にする）
  - JSON応答のパースヘルパー
  - system_instruction のサポート
"""

import subprocess
import re
import os
import json
import time


class GeminiClient:
    """
    Gemini CLI を安全に呼び出すためのクライアントクラス。
    
    subprocess経由でGemini CLIを起動し、stdin/stdoutで通信する。
    レート制限（429）検出時はExponential Backoffで自動リトライする。
    """
    
    def __init__(self, timeout: int = 300, max_retries: int = 3, mock_mode: bool = False):
        """
        Args:
            timeout: CLI呼出しのタイムアウト秒数
            max_retries: 429エラー時の最大リトライ回数
            mock_mode: Trueの場合、実際のAPIを叩かずモック応答を返す
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.mock_mode = mock_mode

    def generate(self, prompt: str, system_instruction: str = None, cwd: str = None) -> str:
        """
        Gemini CLIにプロンプトを送信し、応答テキストを取得する。

        Args:
            prompt: ユーザープロンプト
            system_instruction: システム指示（プロンプトの先頭に付加される）
            cwd: コマンド実行時のカレントディレクトリ
        Returns:
            str: Geminiの応答テキスト（ANSIコード除去済み）
        """
        if self.mock_mode:
            return self._mock_generate(prompt, system_instruction)

        # system_instructionがある場合、プロンプトの先頭に付加
        full_prompt = prompt
        if system_instruction:
            full_prompt = f"以下のシステム指示に従ってください:\n{system_instruction}\n\n---\n\n{prompt}"
        
        if cwd is None:
            cwd = os.getcwd()
        
        retries = 0
        base_delay = 2
        
        while retries <= self.max_retries:
            try:
                result = subprocess.run(
                    ["gemini"],
                    input=full_prompt,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=self.timeout,
                    shell=True
                )
                
                if result.returncode != 0:
                    out_err = (result.stderr + result.stdout).lower()
                    if ("429" in out_err or "quota" in out_err or "rate limit" in out_err):
                        if retries < self.max_retries:
                            delay = base_delay * (2 ** retries)
                            print(f"[!] API Rate Limit. Retrying in {delay}s... ({retries+1}/{self.max_retries})")
                            time.sleep(delay)
                            retries += 1
                            continue
                    raise RuntimeError(
                        f"Gemini CLI Failed (Exit Code {result.returncode}):\n{result.stderr}\n{result.stdout}"
                    )
                
                return self._sanitize(result.stdout)
                
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"Gemini CLI timed out after {self.timeout}s.")
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Error calling Gemini CLI: {str(e)}")
        
        raise RuntimeError("Max retries exceeded due to rate limits.")

    def generate_json(self, prompt: str, system_instruction: str = None, cwd: str = None) -> dict:
        """
        Geminiにプロンプトを送信し、応答をJSONとしてパースして返す。
        
        JSONが直接パースできない場合、応答テキストからJSON部分を正規表現で抽出する。

        Args:
            prompt: ユーザープロンプト（JSON出力を要求する内容にすること）
            system_instruction: システム指示
            cwd: カレントディレクトリ
        Returns:
            dict or list: パースされたJSON
        Raises:
            ValueError: JSONが抽出・パースできなかった場合
        """
        raw = self.generate(prompt, system_instruction, cwd)
        
        # まず直接パースを試みる
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        
        # Markdownのコードブロック内のJSONを抽出
        code_block = re.search(r'```(?:json)?\s*\n(.*?)\n```', raw, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass
        
        # 配列 [...] またはオブジェクト {...} を抽出
        json_match = re.search(r'[\[{].*[\]}]', raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        raise ValueError(f"Failed to parse JSON from Gemini response.\nRaw response:\n{raw[:500]}")

    def _mock_generate(self, prompt: str, system_instruction: str = None) -> str:
        """テスト用モック応答"""
        time.sleep(0.05)
        
        if "eagerness" in prompt.lower() or "自発性" in prompt:
            return '[Eagerness: 75] 議論に貢献したい点があります。'
        
        if "json" in prompt.lower():
            return '{"status": "mock", "message": "これはモック応答です"}'
            
        if "ゲート基準が満たされているか" in prompt:
            return "基準を満たしています。[GATE_PASSED: true]"
        
        return "これはモック応答です。実際のGemini CLIは呼び出されていません。"

    @staticmethod
    def _sanitize(raw_text: str) -> str:
        """ANSIエスケープシーケンスを除去する"""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', raw_text).strip()


if __name__ == "__main__":
    # 簡易テスト
    client = GeminiClient(mock_mode=True)
    print("Mock test:", client.generate("Hello"))
    print("Mock JSON test:", client.generate_json('Return JSON: {"test": true}'))
