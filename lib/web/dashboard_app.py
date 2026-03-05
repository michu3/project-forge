"""
dashboard_app.py - Project Forge リアルタイム可視化ダッシュボードAPI

ローカルの projects/latest_state.json を読み取り、
フロントエンドへREST APIで状態を配信する軽量なFastAPIサーバー。
"""

import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent.parent.absolute()
PROJECTS_DIR = BASE_DIR / "projects"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Project Forge Dashboard API")

# フロントエンド開発時のCORS許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開発用
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SPA用マウント準備 (後ほど実装するフロントエンドをマウントする想定)
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/api/state")
async def get_latest_state():
    """現在アクティブなプロジェクトの最新状態を取得する"""
    state_file = PROJECTS_DIR / "latest_state.json"
    
    if not state_file.exists():
        # まだ何も実行されていない場合の初期状態
        return {
            "project_brief": "待機中...",
            "current_phase": "none",
            "status": "No active project",
            "turn": 0,
            "max_turns": 0,
            "current_speaker": None,
            "history": [],
            "roles": {}
        }
        
    try:
        data = json.loads(state_file.read_text(encoding='utf-8'))
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read state: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """インデックスHTMLを提供する"""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding='utf-8')
    return "<h1>Project Forge Dashboard is starting... (index.html not found)</h1>"

if __name__ == "__main__":
    import uvicorn
    # `uvicorn lib.dashboard_app:app --reload` で起動する想定だが、単体起動も可能に
    uvicorn.run("dashboard_app:app", host="0.0.0.0", port=8000, reload=True)
