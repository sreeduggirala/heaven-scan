# Heaven Scan

Heaven Scanner is a **FastAPI-based webhook service** that listens for
new token launches on the **Heaven DEX** via **Helius webhooks**,
enriches them with **DEXScreener data**, and broadcasts formatted alerts
to a **Telegram channel**.

---

## Features

- **Webhook listener** for `CreateStandardLiquidityPoolEvent` from
  Heaven DEX
- **DEXScreener integration**: enriches new tokens with price, market
  cap, liquidity, and volume
- **Telegram bot notifications** with markdown formatting
- **Deduplication** to prevent duplicate alerts
- **Modular design** for easy filtering and future enhancements

---

## Architecture

    Helius Webhook (Heaven Program)
              ↓
       FastAPI Endpoint (/webhooks/helius)
              ↓
        Fetch DEXScreener Pair
              ↓
       Heaven-only pair filter
              ↓
      Telegram Alert via Telethon

---

## Requirements

- Python 3.10+
- [Helius API key](https://www.helius.xyz/)
- Telegram Bot API credentials (`TG_API_ID`, `TG_API_HASH`,
  `TG_BOT_TOKEN`)
- A Telegram channel with the bot added and permission to post

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/heaven-scanner.git
cd heaven-scanner
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
```

### 3. Set environment variables

Create a `.env` file:

    TG_API_ID=123456
    TG_API_HASH=your_api_hash
    TG_CHANNEL=-1001234567890
    TG_BOT_TOKEN=123456:ABC-your-bot-token

### 4. Run the app

```bash
python app.py
```

The app will expose:

- `POST /webhooks/helius` -- endpoint for Helius to send events
- `GET /healthz` -- health check

---

## Helius Webhook Setup

Create a webhook that listens to the Heaven DEX program and points to
your server:

```bash
curl -X POST "https://api.helius.xyz/v0/webhooks?api-key=YOUR_KEY"   -H "Content-Type: application/json"   -d '{
    "webhookURL": "https://your-domain.com/webhooks/helius",
    "transactionTypes": ["ALL"],
    "accountAddresses": ["pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"],
    "webhookType": "enhanced"
  }'
```

---

## Deployment

### **Option A: systemd (recommended)**

```bash
sudo nano /etc/systemd/system/heaven-scanner.service
```

    [Unit]
    Description=Heaven Scanner FastAPI
    After=network.target

    [Service]
    WorkingDirectory=/opt/heaven-scanner
    EnvironmentFile=/opt/heaven-scanner/.env
    ExecStart=/opt/heaven-scanner/venv/bin/python /opt/heaven-scanner/app.py
    Restart=always
    User=ubuntu
    Group=ubuntu

    [Install]
    WantedBy=multi-user.target

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable heaven-scanner
sudo systemctl start heaven-scanner
sudo journalctl -u heaven-scanner -f
```

### **Option B: Docker Compose**

```yaml
version: "3.9"
services:
  app:
    build: .
    env_file: .env
    ports:
      - "127.0.0.1:8080:8080"
    restart: always
```

Run:

```bash
docker compose up -d
docker compose logs -f
```

---

## File Overview

- **app.py** -- FastAPI webhook server, processes events, sends to
  Telegram
- **dexscreener.py** -- Fetches and formats data from DEXScreener
- **telegram.py** -- Handles Telegram bot connection and messaging
- **.env** -- Environment variables
- **requirements.txt** -- Python dependencies

---

## Future Enhancements

- Add **post-launch performance filters** (e.g., liquidity thresholds
  after X mins)
- Track **holder count** and **trading activity**
- Support **multi-channel** (raw + filtered alerts)

---

## License

MIT License
