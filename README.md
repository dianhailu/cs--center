# CS Midplatform

Multi-product / multi-country customer-service mid-platform.

- **System of record**: Postgres conversations & messages
- **First channel adapter**: LiveAgent (`pingo.ladesk.com` → workspace `pingo-id`)
- **Agent console**: Next.js
- **Workers**: Outbox push to LiveAgent, AI FAQ loop, compensation polling

## Quick start

```bash
cd /Users/lu/Desktop/cursor/cs-midplatform
cp .env.example .env   # already seeded credentials if you copied from liveagent-cs-agent

# infra (optional — local default uses SQLite + in-memory event bus)
# docker compose up -d postgres redis

# backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.api.main:app --host 0.0.0.0 --port 8080 --reload
# another terminal
python -m app.worker.main

# web
cd ../apps/web
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8080 npm run dev
```

Login: `agent@pingo.com` / `agent123`

## LiveAgent webhook

After seed, note printed `SEED_CONNECTION_ID`.

Public URL example (ngrok / cloudflared):

`POST https://<public-host>/api/webhooks/liveagent/<CONNECTION_ID>`

Header: `X-Webhook-Secret: <WEBHOOK_SECRET>`

Body JSON:

```json
{ "ticket_id": "{$conversationid}", "event": "customer_message" }
```

See [scripts/liveagent_rules.md](scripts/liveagent_rules.md).

## Smoke test

```bash
cd backend && source .venv/bin/activate
python ../scripts/e2e_smoke.py
```

## Production deploy (GitHub + Cloudflare)

See **[DEPLOY.md](DEPLOY.md)** for:

- push to GitHub
- Cloudflare Pages for `apps/web`
- VPS + Docker Compose + Cloudflare Tunnel for API/worker
- LiveAgent webhook URL

## Layout

- `backend/app` – API, worker, models, LiveAgent adapter, AI
- `apps/web` – agent console (static export for Pages)
- `docker-compose.yml` – local/dev Postgres, Redis, API/worker
- `docker-compose.prod.yml` – production stack + optional cloudflared
- `deploy/cloudflared/` – Tunnel config examples
