# Deploy: GitHub + Cloudflare Pages + Tunnel

目标架构：

```text
GitHub repo
  ├─ apps/web  ──CI──► Cloudflare Pages  (cs.your-domain.com)
  └─ backend   ──VPS + docker compose──► Cloudflare Tunnel (api.your-domain.com)
                                              ▲
                                      LiveAgent webhook
```

## 0. 推送到 GitHub

本机若未装 `gh`，用网页新建空仓库后执行：

```bash
cd /Users/lu/Desktop/cursor/cs-midplatform
# 去掉本地假 remote（若还指向自身 .git）
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/<YOU>/<REPO>.git

git add .
git status   # 确认没有 .env / cs.db / secrets
git commit -m "feat: cs midplatform with LiveAgent adapter and deploy configs"
git push -u origin main
```

**不要提交**：`.env`、`.env.production`、`backend/cs.db`、`deploy/cloudflared/*.json`

## 1. 后端（VPS + Docker + Tunnel）

在任意小 VPS（Ubuntu 即可）：

```bash
git clone https://github.com/<YOU>/<REPO>.git
cd <REPO>
cp .env.production.example .env.production
# 编辑密钥、LIVEAGENT_*、CORS_ORIGINS、SEED_AGENT_PASSWORD
```

安装 Docker 后：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
curl -s http://127.0.0.1:8080/health
```

### Cloudflare Tunnel

在本机或服务器：

```bash
cloudflared tunnel login
cloudflared tunnel create cs-midplatform
cloudflared tunnel route dns cs-midplatform api.your-domain.com
```

复制凭证：

```bash
cp ~/.cloudflared/<TUNNEL_ID>.json deploy/cloudflared/
cp deploy/cloudflared/config.example.yml deploy/cloudflared/config.yml
# 编辑 tunnel id / credentials-file / hostname
```

启动 Tunnel 容器：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production --profile tunnel up -d
```

验证：`https://api.your-domain.com/health`

### LiveAgent 规则

Webhook：

`https://api.your-domain.com/api/webhooks/liveagent/<CONNECTION_ID>`

Header：`X-Webhook-Secret: <WEBHOOK_SECRET>`

详见 [scripts/liveagent_rules.md](scripts/liveagent_rules.md)。  
服务器首次启动后看 API/worker 日志里的 `SEED_CONNECTION_ID`。

生产请设：`LIVEAGENT_DRY_RUN=false`

## 2. 前端（Cloudflare Pages）

### 方式 A：GitHub Actions（已写好）

仓库配置：

**Secrets**

- `CLOUDFLARE_API_TOKEN`（Pages Edit 权限）
- `CLOUDFLARE_ACCOUNT_ID`

**Variables**

- `NEXT_PUBLIC_API_BASE` = `https://api.your-domain.com`
- `CLOUDFLARE_PAGES_PROJECT` = `cs-midplatform`（可选）

推送到 `main` 且改动 `apps/web/**` 时自动构建发布。

### 方式 B：Cloudflare 控制台直连 GitHub

1. Workers & Pages → Create → Connect to Git  
2. Root directory: `apps/web`  
3. Build command: `npm ci && npm run build`  
4. Build output: `out`  
5. Env var: `NEXT_PUBLIC_API_BASE=https://api.your-domain.com`

自定义域名：`cs.your-domain.com` → Pages 项目。

## 3. CORS

`.env.production`：

```env
CORS_ORIGINS=https://cs.your-domain.com,https://<project>.pages.dev
```

改完后：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d api worker
```

## 4. 验收清单

- [ ] `https://api.your-domain.com/health` 返回 ok  
- [ ] Pages 登录页可打开，能登录  
- [ ] 坐席台能拉到会话列表  
- [ ] LiveAgent 测试消息能进中台（webhook 或 worker poll）  
- [ ] 坐席回复后客户侧可见（`DRY_RUN=false`）  

## 5. 本地静态构建自检

```bash
cd apps/web
NEXT_PUBLIC_API_BASE=https://api.your-domain.com npm run build
ls out
```
