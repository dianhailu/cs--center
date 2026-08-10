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
LIVEAGENT_AUTO_TRANSFER=true
LIVEAGENT_AGENT_EMAIL=<PinGo CS agent email>
```

`LIVEAGENT_AUTO_TRANSFER=true`（默认）时，worker 在 `post_reply` 前会先通过 LiveAgent attendants API 把会话转给 `LIVEAGENT_AGENT_EMAIL`，减少人工点击 ring/接听弹窗的依赖。设为 `false` 可关闭。

### LiveAgent 常在线（Devices keep-alive）

`LIVEAGENT_KEEP_ONLINE=true`（默认）时，worker 启动后立刻、并每 `LIVEAGENT_KEEP_ONLINE_INTERVAL_SEC`（默认 60）秒，通过 v3 Devices API 把 PinGo CS 的 **chat device** 设为 online（`online_status/preset_status=N`），并更新 department 在线状态，让访客 widget 能发起 livechat。

与 auto-transfer **互补、互不替代**：
- keep-online：访客侧能看到客服在线并开始聊天
- auto-transfer：会话进来后转给 `LIVEAGENT_AGENT_EMAIL`，再由 AI/`post_reply` 回复

可选环境变量：
```env
LIVEAGENT_KEEP_ONLINE=true
LIVEAGENT_KEEP_ONLINE_INTERVAL_SEC=60
# LIVEAGENT_AGENT_USER_ID=<optional agent id>
# LIVEAGENT_CHAT_DEPARTMENT_ID=<optional department_id, e.g. default>
```

日志关键字：`keep_online ok` / `keep_online agent=... still offline`。若反复出现 still offline，可能仍需在 LiveAgent 面板保留一次浏览器会话，或确认该 agent 已有 Web chat device（PinGo 5.67.7 的 `POST /devices` 只能创建 phone device，chat device 需面板侧已存在）。

离线临时兜底（不改代码）：可在 LiveAgent 配置 chatbot/离线消息；本仓库当前不集成 chatbot。

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

## 4. Smart 晚上学习历史会话

Worker 内置定时任务：每天在 `HISTORY_LEARN_HOUR`（默认 **22**）`HISTORY_LEARN_TIMEZONE`（默认 **Asia/Jakarta**）从 DB 全量重建 `backend/knowledge/history_pairs.json`（含历史 + 当天新会话）。知识目录已挂载到 API/worker。

首次部署若知识文件为空，worker 启动时会立刻做一次 **initial** 全量学习。也可手动触发：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec worker \
  python scripts/build_history_knowledge.py
```

日志关键字：`history learn start` / `history learn finished`。

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker | grep 'history learn'
```

## 5. 验收清单

- [ ] `https://api.cs.originmount.com/health` 返回 ok  
- [ ] `https://cs.originmount.com` 登录页可打开并登录  
- [ ] 坐席台能拉到会话列表  
- [ ] LiveAgent 测试消息能进中台  
- [ ] 坐席回复后客户侧可见（`DRY_RUN=false`）  
- [ ] worker 日志出现 `learn=True@22:00 Asia/Jakarta`；空知识时有 `history learn start reason=initial`  
- [ ] worker 日志出现 `keep_online=True` 与周期性 `keep_online ok`；访客 widget 可发起 livechat  

## 6. 本地静态构建自检

```bash
cd apps/web
NEXT_PUBLIC_API_BASE=https://api.cs.originmount.com npm run build
ls out
```
