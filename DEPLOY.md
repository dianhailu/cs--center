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
AI_SEND_TO_CUSTOMER=false
```

可选管理员与默认产品/国家：

```env
DEFAULT_PRODUCT_CODE=pingo
DEFAULT_COUNTRY_CODE=ID
# SEED_ADMIN_EMAIL=admin@example.com
# SEED_ADMIN_PASSWORD=change-me-admin-password
```

启动 seed 会补齐 `countries`/`products`、把 FAQ 标为 `product_code=pingo`、现有坐席迁为 `agent`。管理台：`/admin/`（product_admin+）。新部署示例默认 `AI_SEND_TO_CUSTOMER=false`；质量就绪后可在生产 `.env.production` 设为 `true`（见下节）。

`LIVEAGENT_AUTO_TRANSFER=true`（默认）时，worker 在 `post_reply` 前会先通过 LiveAgent attendants API 把会话转给 `LIVEAGENT_AGENT_EMAIL`，减少人工点击 ring/接听弹窗的依赖。设为 `false` 可关闭。

`LIVEAGENT_PANEL_ACCEPT=true`（默认）时，worker 在发送前还会用 agent `LoginKey` 调面板 RPC `ChatAnswererRpc.pickUpChat`（+ `joinOperator`），相当于点弹窗「回复」，可清掉访客侧「等待接入」。随后用 `ChatMessenger.createAnswer` 写入 **type C** 消息组（`chatId` 必须是 type-C message group UUID，不是 conversation/ticket id；用错 id 时 LA 会误报「您没有权限」）。失败时回退公开 API `post_reply`（type 5，仅坐席/中台可见）。设为 `false` 可关闭面板接入。

### AI / OpenAI（香港 VPS 地区限制）

阿里云 HK 直连 `api.openai.com` 常返回 `403 unsupported_country_region_territory`。密钥本身可能有效，但官方 endpoint 从 HK 不可达。**新加坡出口一般可用。**

推荐：VPS 经新加坡 VPN/HTTP(S)/SOCKS 代理访问官方 API（agent 回复 + KB 自动翻译共用）：

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_PROXY=http://user:pass@host:port
# 或 HTTPS_PROXY=... / HTTP_PROXY=... / ALL_PROXY=... / socks5://host:port
```

备选：把 `OPENAI_BASE_URL` 指到 OpenAI 兼容网关（不走 VPN）。改完后需 `up -d --build` api + worker。

### AI 是否发给客户（`AI_SEND_TO_CUSTOMER`）

- **示例 / 新部署默认：`false`**（代码与 `.env*.example` 保持 false，避免误开）：Smart 仍生成并写入中台会话（客服可见 `local_only` 气泡），**不**经 outbox/`post_reply` 发给 LiveAgent 访客。人工客服在中台的回复仍正常投递。
- 质量就绪后可在生产接线：`.env.production` 设 `AI_SEND_TO_CUSTOMER=true`，然后 `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --force-recreate api worker`（必要时 `--build`）。临时关闭：改回 `false` 并同样 recreate。
- 注意：公开 API `post_reply` 写入 type 5，访客 widget 通常看不到。`LIVEAGENT_PANEL_ACCEPT` 会先 `pickUpChat`，再用 type-C group id 调 `createAnswer` 让访客可见。与本开关独立。

与 auto-transfer / keep-online 独立：关闭投递后不会因 AI 触发 transfer+回复。

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

日志关键字：`history learn start` / `history learn finished` / `faq auto-promote`。

学习完成后（`FAQ_AUTO_PROMOTE=true`，默认）会把高质量「客户→人工坐席」回复晋升进 `faq.json`（每晚最多 `FAQ_PROMOTE_MAX_PER_NIGHT`，默认 50），带来源标记 `source=ai_learn`。

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker | grep -E 'history learn|faq auto-promote'
```

### FAQ / Excel 知识库 + 未知问题教答

- 主动 FAQ：`backend/knowledge/faq.json`（含 Excel V2 导入 + 旧库合并 + 人工教答），见 [backend/knowledge/README.md](backend/knowledge/README.md)。
- 低置信 / handoff 时写入挂载目录 `unknown_questions.jsonl`（不投递客户）。
- 列表 / 教答：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec worker \
  python scripts/list_unknown_questions.py
docker compose -f docker-compose.prod.yml --env-file .env.production exec worker \
  python scripts/teach_unknown.py uq_... --answer "..."
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
