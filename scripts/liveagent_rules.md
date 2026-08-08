# LiveAgent automation rule setup (PinGo)

Workspace: `pingo-id`  
LiveAgent: `https://pingo.ladesk.com`

## 1. Get connection id

```bash
cd /Users/lu/Desktop/cursor/cs-midplatform/backend
source .venv/bin/activate
python -m app.seed
# prints SEED_CONNECTION_ID=...
```

## 2. Expose API publicly (dev)

Current seeded connection id: `2855b824-044d-4f48-abc8-5b3cd1594052`

```bash
# example
ngrok http 8080
# or
cloudflared tunnel --url http://127.0.0.1:8080
```

Webhook URL:

`https://<public-host>/api/webhooks/liveagent/2855b824-044d-4f48-abc8-5b3cd1594052`

## 3. Create rule in LiveAgent

Path: **Configuration → Automation → Rules** (自动程序 → 规则)

Suggested rule:

- **Trigger**: Conversation created / Message added from customer (use the closest available event)
- **Conditions** (optional):
  - Tag does not contain `ai_replied`
  - Tag does not contain `ai_handoff`
- **Action**: HTTP Request
  - Method: `POST`
  - URL: webhook URL above
  - Headers:
    - `Content-Type: application/json`
    - `X-Webhook-Secret: dev-secret` (or value of `WEBHOOK_SECRET`)
  - Body:

```json
{
  "ticket_id": "{$conversationid}",
  "code": "{$conversationcode}",
  "event": "customer_message"
}
```

> Exact macro names vary by LiveAgent version. If macros differ, send whatever ticket id field the rule UI exposes.

## 4. Verify

1. Create / reply on a test ticket in LiveAgent  
2. Check API logs for webhook hit  
3. Open agent console → Human queue / All open  
4. Worker should run AI and/or push replies via Outbox  

## 5. Production notes

- Set `LIVEAGENT_DRY_RUN=false` only after dry-run looks correct  
- Rotate webhook secret  
- Prefer HTTPS public endpoint with rate limits  
