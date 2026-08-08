# Deploy: GitHub + Cloudflare Pages + Tunnel

目标域名（PinGo）：

| 用途 | 域名 |
|------|------|
| 坐席台（Pages） | `https://cs.originmount.com` |
| API / Webhook（Tunnel） | `https://api.cs.originmount.com` |

```text
GitHub dianhailu/cs--center
  ├─ apps/web  ──► Cloudflare Pages  → cs.originmount.com
  └─ backend   ──► VPS + docker + Tunnel → api.cs.originmount.com
                                              ▲
                                      LiveAgent webhook
```

前提：`originmount.com` 的 DNS 已接入 Cloudflare（橙色云或至少可由 Cloudflare 管理 DNS）。

## 0. 代码仓库

已推送：https://github.com/dianhailu/cs--center

**不要提交**：`.env`、`.env.production`、`backend/cs.db`、`deploy/cloudflared/*.json`

## 1. 前端（Cloudflare Pages）— 可先做

1. Cloudflare → **Workers & Pages** → Create → **Connect to Git** → `dianhailu/cs--center`
2. 构建设置：
   - Root directory: `apps/web`
   - Build command: `npm ci && npm run build`
   - Build output: `out`
3. Environment variable：
   - `NEXT_PUBLIC_API_BASE` = `https://api.cs.originmount.com`
4. 部署完成后：**Custom domains** → 添加 `cs.originmount.com`  
   （Cloudflare 会自动加 CNAME；若域名已在本账号下，通常一键即可）

此时页面能打开，但登录要等 API 上线。

## 2. 后端（VPS + Docker + Tunnel）

在任意小 VPS（Ubuntu 即可）：

```bash
git clone https://github.com/dianhailu/cs--center.git
cd cs--center
cp .env.production.example .env.production
# 编辑密钥、LIVEAGENT_*、CORS_ORIGINS、SEED_AGENT_PASSWORD
```

`.env.production` 关键至少保证：

```env
CORS_ORIGINS=https://cs.originmount.com
LIVEAGENT_DRY_RUN=false
```

安装 Docker 后：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
curl -s http://127.0.0.1:8080/health
```

### Cloudflare Tunnel

本机或服务器（需已安装 `cloudflared`，且用管 `originmount.com` 的 Cloudflare 账号登录）：

```bash
cloudflared tunnel login
cloudflared tunnel create cs-midplatform
cloudflared tunnel route dns cs-midplatform api.cs.originmount.com
```

复制凭证：

```bash
cp ~/.cloudflared/<TUNNEL_ID>.json deploy/cloudflared/
cp deploy/cloudflared/config.example.yml deploy/cloudflared/config.yml
# 编辑 tunnel id / credentials-file / hostname → api.cs.originmount.com
```

启动 Tunnel：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production --profile tunnel up -d
```

验证：`https://api.cs.originmount.com/health`

### LiveAgent 规则

Webhook：

`https://api.cs.originmount.com/api/webhooks/liveagent/<CONNECTION_ID>`

Header：`X-Webhook-Secret: <WEBHOOK_SECRET>`

详见 [scripts/liveagent_rules.md](scripts/liveagent_rules.md)。  
服务器首次启动后看 API/worker 日志里的 `SEED_CONNECTION_ID`。

## 3. CORS（改域名后重启 API）

```env
CORS_ORIGINS=https://cs.originmount.com,https://<project>.pages.dev
```

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d api worker
```

## 4. 验收清单

- [ ] `https://api.cs.originmount.com/health` 返回 ok  
- [ ] `https://cs.originmount.com` 登录页可打开并登录  
- [ ] 坐席台能拉到会话列表  
- [ ] LiveAgent 测试消息能进中台  
- [ ] 坐席回复后客户侧可见（`DRY_RUN=false`）  

## 5. 本地静态构建自检

```bash
cd apps/web
NEXT_PUBLIC_API_BASE=https://api.cs.originmount.com npm run build
ls out
```
