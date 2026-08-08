import os
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.screener_service import ScreenerService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVICE: Optional[ScreenerService] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global SERVICE
    SERVICE = ScreenerService(markets=["KOSPI", "KOSDAQ", "NASDAQ"], poll_interval=60)
    await SERVICE.initialize()
    asyncio.create_task(SERVICE.run_screen())  # 초기 1회 실행
    SERVICE.start()
    yield
    SERVICE.stop()


app = FastAPI(title="KOSPI/KOSDAQ/NASDAQ 4대 기법 실시간 검색기", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(content="<h1>index.html not found</h1>", status_code=404)


@app.get("/api/status")
async def status():
    if not SERVICE:
        raise HTTPException(status_code=503, detail="Service not ready")
    return {
        "is_running": SERVICE.is_running,
        "last_run": SERVICE.last_run.isoformat() if SERVICE.last_run else None,
        "universe_total": len(SERVICE.universe),
        "universe_filtered": len(SERVICE.filtered_universe),
        "signal_count": len(SERVICE.signals),
    }


@app.get("/api/signals")
async def get_signals(strategy: Optional[str] = Query(None), market: Optional[str] = Query(None)):
    if not SERVICE:
        raise HTTPException(status_code=503, detail="Service not ready")
    signals = SERVICE.signals
    if strategy:
        signals = [s for s in signals if s.strategy == strategy]
    if market:
        signals = [s for s in signals if s.market == market]
    return {"signals": [s.__dict__ if not hasattr(s, "__dataclass_fields__") else s.__dict__ for s in signals]}


@app.get("/api/strategies")
async def strategies():
    return {
        "strategies": [
            {
                "id": "256",
                "name": "256 기법",
                "desc": "이평선 밀집 후 20일선이 5/6일선을 돌파하는 자리. (A: 5/20/60 이평 3% 밀집, B: 5이평>20이평, C: 6이평>20이평, D: 거래량 200% 증가)"
            },
            {
                "id": "babgeures",
                "name": "밥그릇 3번",
                "desc": "장기 하락 후 112/224일선 돌파. (A: 100일전 종가>당일, B/C: 112/224선 돌파, D: 5>20>60 정배열)"
            },
            {
                "id": "gongguri",
                "name": "공구리 기법",
                "desc": "단기 매물대 강하게 돌파. (A: 5봉 신고가, B: 20선 돌파, C: 볼린저 상한선 이상, D: 일목 선행스팬 위)"
            },
            {
                "id": "odol",
                "name": "오돌이 기법",
                "desc": "주가 하락 후 5일선 방향 전환 및 돌파. (A: 20>60>112 또는 224 위, B: 5봉 -5% 이상, C: 5이평 상승전환, D: 종가 5이평 돌파, E: 거래량 150% 증가)"
            },
        ]
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if not SERVICE:
        await websocket.send_text(json.dumps({"error": "Service not ready"}))
        await websocket.close()
        return
    SERVICE.subscribe(websocket)
    try:
        # 최신 상태 즉시 전송
        await websocket.send_text(json.dumps(SERVICE.to_dict(), ensure_ascii=False, default=str))
        while True:
            try:
                msg = await websocket.receive_text()
                data = json.loads(msg)
                if data.get("action") == "refresh":
                    await SERVICE.run_screen()
                elif data.get("action") == "status":
                    await websocket.send_text(json.dumps(SERVICE.to_dict(), ensure_ascii=False, default=str))
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.debug("ws msg error: %s", e)
                await websocket.send_text(json.dumps({"error": str(e)}))
    except WebSocketDisconnect:
        pass
    finally:
        SERVICE.unsubscribe(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=False)
