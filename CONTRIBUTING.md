# CONTRIBUTING — Project Forge への貢献ガイド

Project Forge は「AI SIベンダーシステム」の開発リポジトリです。
このドキュメントでは、コードの変更、ドキュメントの追加、および機能開発の進め方を説明します。

---

## 📋 開発フロー

```
main ← PR (Squash & Merge)
  └── feature/forge-YYYYMMDD-<brief-slug>  ← AI または人間が作成
```

### 人間による開発
1. `main` からブランチを作成: `git checkout -b feature/my-feature main`
2. 変更・コミット・Push
3. PR を作成（GitHub UI または `gh pr create`）
4. CI（テスト・Lint）が通ることを確認
5. レビュー → Approve → Squash & Merge

### AI（Project Forge）による開発
Project Forge は案件を受け取ると、以下を自動で行います：
1. 全フェーズ（Discovery → Design → Build → Test）を自律実行
2. `feature/forge-YYYYMMDD-<brief-slug>` ブランチを作成・Push
3. **Draft PR** を自動作成（`ai-generated` ラベル付き）
4. 人間がレビューし、Approve → Merge

---

## 🏃 ローカルでの開発準備

```bash
# 依存関係のインストール
cd workspace/project_forge
pip install -r requirements.txt

# テスト実行（全プラットフォーム）
pytest tests/ -v

# カバレッジ付き
pytest tests/ -v --cov=lib --cov-report=term-missing

# Lintチェック
ruff check lib/ tests/
```

---

## 📦 モジュール構成と責務

| モジュール | 責務 |
|:----------|:-----|
| `forge_orchestrator.py` | エントリポイント。全フェーズのパイプライン管理 |
| `phase_engine.py` | 1フェーズのターンループ・ゲートチェック・成果物生成 |
| `artifact_manager.py` | 成果物の保存・読込・フェーズ間の受渡し |
| `role_generator.py` | フェーズ参加ロールのセットアップ |
| `gemini_client.py` | Gemini CLI 呼出しラッパー（リトライ機能付き） |
| `code_executor.py` | Phase 5: subprocess 実行 + セルフヒーリングループ |
| `cicd_manager.py` | Phase 6: GitHub PR 自動作成（PyGithub / gh CLI） |
| `dashboard_app.py` | FastAPI リアルタイムダッシュボード |

---

## 🚩 CLI フラグ一覧

| フラグ | 説明 |
|:------|:-----|
| `--mock` | Gemini API を呼ばずモック応答で動作確認 |
| `--execute` | Phase 5（セルフヒーリング）を実行（コードを実際に pytest で検証・自動修正） |
| `--pr` | Phase 6（GitHub PR 自動作成）を実行（`GITHUB_TOKEN` / `GITHUB_REPO` 環境変数が必要） |

これらは組み合わせ可能です（例: `--mock --execute --pr`）。

---

## 🌿 ブランチ命名規則

| 種別 | フォーマット | 例 |
|:-----|:------------|:---|
| AI 生成 | `feature/forge-YYYYMMDD-HHMMSS-<slug>` | `feature/forge-20260305-093000-chatbot` |
| 機能追加 | `feature/<name>` | `feature/self-healing` |
| バグ修正 | `fix/<name>` | `fix/gate-check-timeout` |
| ドキュメント | `docs/<name>` | `docs/architecture` |

---

## 🏷️ PR ラベルの説明

| ラベル | 意味 |
|:------|:-----|
| `ai-generated` | Project Forge が自律生成した PR |
| `needs-review` | レビュー待ち（AI 生成 PR に自動付与） |
| `human-generated` | 人間が作成した PR |

---

## 🧪 テストの追加方法

テストは `tests/` ディレクトリに格納します。
命名規則: `test_<モジュール名>.py`

```python
# tests/test_my_module.py の例
import pytest
from lib.my_module import MyClass

def test_my_function():
    obj = MyClass(mock_mode=True)
    result = obj.my_function("入力")
    assert result == "期待値"
```

---

## 🔐 環境変数の管理

| 変数名 | 用途 | 取得元 |
|:------|:-----|:------|
| `GITHUB_TOKEN` | GitHub PR 自動作成 | [Personal Access Token](https://github.com/settings/tokens)（`repo` スコープ） |
| `GITHUB_REPO` | 対象リポジトリ | `owner/repo-name` 形式で設定 |

**⚠️ 重要**: これらの値をコードにハードコードしないでください。環境変数または `.env` ファイルで管理してください。

```bash
# .env ファイルの例（リポジトリには含めない）
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxx
GITHUB_REPO=your-org/your-repo
```

---

## 📝 コミットメッセージ規則

[Conventional Commits](https://www.conventionalcommits.org/) に従います：

```
feat: 新機能
fix: バグ修正
docs: ドキュメントのみの変更
test: テストの追加・修正
refactor: リファクタリング（バグ修正や機能追加なし）
chore: ビルドプロセスや補助ツールの変更
```

---

## ❓ 質問・提案

Issue を作成するか、既存の Issue にコメントしてください。
