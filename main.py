import asyncio
import json
import time
import logging
from contextlib import asynccontextmanager
from collections import defaultdict
from datetime import datetime
from typing import Optional

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


PAIRS = ["btcusdt", "ethusdt", "bnbusdt"]
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
MAX_CONNECTIONS = 50


latest_prices: dict = {}          
message_queue: Optional[asyncio.Queue] = None          
connected_clients: set = set()    
connection_count: int = 0



class ConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> bool:
        if len(self.active) >= MAX_CONNECTIONS:
            await ws.close(code=1008, reason="Server at capacity")
            return False
        await ws.accept()
        self.active.add(ws)
        log.info(f"Client connected. Total: {len(self.active)}")
        return True

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)
        log.info(f"Client disconnected. Total: {len(self.active)}")

    async def broadcast(self, data: dict):
        dead = set()
        msg = json.dumps(data)
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def build_binance_url() -> str:
    streams = "/".join(f"{p}@ticker" for p in PAIRS)
    return f"{BINANCE_WS_BASE}/{streams}" if len(PAIRS) == 1 else \
           f"wss://stream.binance.com:9443/stream?streams={streams}"


def parse_ticker(raw: dict) -> Optional[dict] :
    """Parse a Binance ticker payload (handles both single and combined streams)."""
    data = raw.get("data", raw)         
    if data.get("e") != "24hrTicker":
        return None
    try:
        return {
            "symbol":     data["s"],
            "last_price": float(data["c"]),
            "change_pct": float(data["P"]),
                        "timestamp": datetime.utcfromtimestamp(
                    data.get("T", int(time.time() * 1000)) / 1000
                ).isoformat() + "Z",
            }
    except Exception as e:
        log.warning(f"Parsing error {e},data :{data}")
        return None

    
async def binance_listener(queue: asyncio.Queue):
    url = build_binance_url()
    backoff = 1
    while True:
        try:
            log.info(f"Connecting to Binance: {url}")
            async with websockets.connect(url, ping_interval=20) as ws:
                backoff = 1
                async for raw_msg in ws:
                    payload = json.loads(raw_msg)
                    ticker = parse_ticker(payload)
                    if ticker:
                        latest_prices[ticker["symbol"]] = ticker
                        await queue.put(ticker)
        except Exception as e:
            log.warning(f"Binance connection error: {e}. Retrying in {backoff}s…")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)



async def broadcaster(queue: asyncio.Queue):
    while True:
        ticker = await queue.get()
        if manager.active:
            await manager.broadcast(ticker)



@asynccontextmanager
async def lifespan(app: FastAPI):
    global message_queue
    message_queue = asyncio.Queue(maxsize=1000)
    asyncio.create_task(binance_listener(message_queue))
    asyncio.create_task(broadcaster(message_queue))
    log.info("Background tasks started.")
    yield
    log.info("Shutting down.")



limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Crypto Price WebSocket", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)



@app.get("/price")
@limiter.limit("30/minute")
async def get_price(request: Request, symbol: str = "BTCUSDT"):
    symbol = symbol.upper()
    if symbol not in latest_prices:
        raise HTTPException(status_code=404, detail=f"No data yet for {symbol}")
    return latest_prices[symbol]


@app.get("/prices")
@limiter.limit("30/minute")
async def get_all_prices(request: Request):
    return latest_prices


@app.get("/health")
async def health():
    return {"status": "ok", "clients": len(manager.active), "pairs": list(latest_prices.keys())}



@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    ok = await manager.connect(ws)
    if not ok:
        return
    
    if latest_prices:
        for ticker in latest_prices.values():
            await ws.send_text(json.dumps(ticker))
    try:
        while True:
            await ws.receive_text()   
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)



@app.get("/", response_class=HTMLResponse)
async def demo_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Crypto Live Prices</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;padding:2rem}
  h1{text-align:center;color:#f0b90b;margin-bottom:1.5rem;font-size:1.8rem}
  #grid{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin-bottom:2rem}
  .card{background:#1a1d27;border:1px solid #2a2d3a;border-radius:12px;padding:1.2rem 1.8rem;min-width:200px;text-align:center}
  .card .sym{font-size:1rem;color:#aaa;margin-bottom:.4rem}
  .card .price{font-size:2rem;font-weight:700;color:#fff}
  .card .chg{font-size:1rem;margin-top:.3rem}
  .up{color:#0ecb81} .dn{color:#f6465d}
  #log{background:#1a1d27;border:1px solid #2a2d3a;border-radius:8px;padding:1rem;height:200px;overflow-y:auto;font-size:.8rem;font-family:monospace}
  #status{text-align:center;margin-bottom:1rem;font-size:.9rem;color:#aaa}
  span.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#f6465d;margin-right:6px}
  span.dot.on{background:#0ecb81}
</style>
</head>
<body>
<h1>⚡ Crypto Live Prices</h1>
<div id="status"><span class="dot" id="dot"></span><span id="stxt">Connecting…</span></div>
<div id="grid"></div>
<div id="log"></div>
<script>
const cards={};
function upsertCard(d){
  const g=document.getElementById('grid');
  if(!cards[d.symbol]){
    const el=document.createElement('div');
    el.className='card'; el.id='c_'+d.symbol;
    el.innerHTML=`<div class="sym">${d.symbol}</div><div class="price" id="p_${d.symbol}">-</div><div class="chg" id="ch_${d.symbol}">-</div>`;
    g.appendChild(el); cards[d.symbol]=true;
  }
  const sign=d.change_pct>=0?'+':'';
  const cls=d.change_pct>=0?'up':'dn';
  document.getElementById('p_'+d.symbol).textContent='$'+parseFloat(d.last_price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const ch=document.getElementById('ch_'+d.symbol);
  ch.textContent=sign+parseFloat(d.change_pct).toFixed(2)+'%';
  ch.className='chg '+cls;
}
function addLog(msg){
  const l=document.getElementById('log');
  const line=document.createElement('div');
  line.textContent=new Date().toLocaleTimeString()+' '+msg;
  l.prepend(line);
  if(l.children.length>100) l.removeChild(l.lastChild);
}
function connect(){
  const ws=new WebSocket(`ws://${location.host}/ws`);
  ws.onopen=()=>{document.getElementById('dot').classList.add('on');document.getElementById('stxt').textContent='Connected';addLog('WebSocket connected')};
  ws.onclose=()=>{document.getElementById('dot').classList.remove('on');document.getElementById('stxt').textContent='Disconnected – reconnecting…';addLog('Disconnected');setTimeout(connect,3000)};
  ws.onmessage=(e)=>{const d=JSON.parse(e.data);upsertCard(d);addLog(`${d.symbol} $${parseFloat(d.last_price).toFixed(2)} (${d.change_pct>0?'+':''}${parseFloat(d.change_pct).toFixed(2)}%)`)};
}
connect();
</script>
</body>
</html>"""
