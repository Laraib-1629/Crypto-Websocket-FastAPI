# Crypto Price WebSocket Project

Real-time BTC/ETH/BNB price streaming via Binance WebSocket → FastAPI server → clients.


## Live Demo
👉 https://crypto-websocket-fastapi.onrender.com/

Open the link to see the live crypto dashboard.

## Architecture

```
Binance WSS ──► binance_listener() ──► asyncio.Queue ──► broadcaster()
                                                               │
                                               ┌──────────────┘
                                               ▼
                                    ConnectionManager.broadcast()
                                               │
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                          Client A         Client B         Client C
```

## Features

| Feature | Details |
|---|---|
| Multiple pairs | BTC/USDT, ETH/USDT, BNB/USDT |
| Local WS server | `ws://localhost:8000/ws` |
| REST API | `GET /price?symbol=BTCUSDT`, `GET /prices` |
| Rate limiting | 30 req/min on REST endpoints |
| Connection limit | Max 50 concurrent WS clients |
| Graceful disconnects | Dead clients removed automatically |
| asyncio.Queue | Fan-out message bus |
| Auto-reconnect | Exponential back-off on Binance drop |
| Demo UI | Browser dashboard at `http://localhost:8000` |
| Docker | Single `docker compose up` |

## Run Locally (without Docker)

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://localhost:8000 for the live dashboard.

## Run with Docker

```bash
docker compose up --build
```

## API Reference

### WebSocket

**Local:**
```
ws://localhost:8000/ws
```
**Production:**
```
wss://crypto-websocket-fastapi.onrender.com/ws
```

```json
{
  "symbol": "BTCUSDT",
  "last_price": 68421.5,
  "change_pct": 1.23,
  "timestamp": "2024-11-01T10:00:00Z"
}
```

### REST

| Method | Path | Description |
|---|---|---|
| GET | `/price?symbol=BTCUSDT` | Latest price for one symbol |
| GET | `/prices` | All latest prices |
| GET | `/health` | Server health + client count |

## Test the WebSocket (CLI)

```bash
# Install wscat
npm install -g wscat

# Local
wscat -c ws://localhost:8000/ws

# Production
wscat -c wss://crypto-websocket-fastapi.onrender.com/ws
```

## Test the REST API

```bash
# Local
curl http://localhost:8000/price?symbol=ETHUSDT

# Production
curl https://crypto-websocket-fastapi.onrender.com/price?symbol=ETHUSDT
```

## 📌 Notes

- Uses secure WebSocket (`wss://`) in production
- Designed using producer-consumer pattern (asyncio.Queue)
- Backend acts as both:
  - WebSocket client (Binance)
  - WebSocket server (clients)

## 👨‍💻 Author

**Laraib Ahmed**

- GitHub: https://github.com/Laraib-1629