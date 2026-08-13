# PinGo CS Knowledge Base

运行时由 API / worker 挂载：`backend/knowledge` → 容器 `/app/knowledge`。

## 文件

| 文件 | 说明 | Git |
|------|------|-----|
| `faq.json` | **主动知识库**（Agent 检索） | 提交 |
| `kb_v2.json` | Excel V2.0 导入快照（41 条） | 提交 |
| `faq_legacy.json` | 导入前旧 FAQ 备份 | 提交 |
| `escalation.json` | 升级部门对照 | 提交 |
| `qa_standards.json` | QA 检查项 | 提交 |
| `history_pairs.json` | 历史人工回复挖掘（晚上学习） | **忽略** |
| `unknown_questions.jsonl` | 未命中/低置信问题流水 | **忽略** |

## 从 Excel 更新 FAQ

```bash
cd backend
pip install openpyxl   # 仅本机导入需要
python scripts/import_kb_xlsx.py /path/to/PinGo_Customer_Service_Knowledge_Base_V2.0.xlsx
```

会：备份旧 `faq.json` → `faq_legacy.json`（仅首次）、写出 `kb_v2.json`、合并去重写入 `faq.json`。

Agent 启动后按文件 mtime 热加载 FAQ，教答后一般无需重启 worker。

## 多语言 FAQ

每条 FAQ 为嵌套三语 + 分类编码：

```json
{
  "id": 1,
  "code": "pingo-product--01",
  "category_slug": "pingo-product",
  "category": { "zh": "产品", "id": "Produk", "en": "Product" },
  "question": { "zh": "...", "id": "...", "en": "..." },
  "answer": { "zh": "...", "id": "...", "en": "..." }
}
```

分类注册表：`categories.json`（slug + 三语 label）。编码格式：`{slug}--{NN}`。

坐席台 `/knowledge/` 或 API（需 agent token）：

- `GET/POST /api/knowledge/faq`、`PUT /api/knowledge/faq/{id}`（支持 `category_slug`、`auto_translate`）
- `GET/POST /api/knowledge/categories`
- `GET /api/knowledge/unknowns`
- `PUT /api/knowledge/unknowns/{id}`（草稿）
- `POST /api/knowledge/unknowns/{id}/resolve`（答案入库 FAQ）

创建/更新时可只填一种语言；`auto_translate: true`（默认）时若配置了 `OPENAI_API_KEY` 会补全另外两种语言。

写入使用文件锁 + 原子替换；FAQ 按 mtime 热加载。

## 未知问题

当 history/FAQ 不够自信（handoff / weak retrieval）时，worker 追加一行到 `unknown_questions.jsonl`（Jakarta 日期）。  
**不会**因此把内容发给客户；客户投递仍由 `AI_SEND_TO_CUSTOMER` 控制（默认 `false`）。

```bash
# 容器内或本机（PYTHONPATH=/app）
python scripts/list_unknown_questions.py
python scripts/list_unknown_questions.py --status open --days 7

# 用 unknown id 教答 → 写入 faq.json 并标记 answered
python scripts/teach_unknown.py uq_YYYYMMDD_xxxxxxxx --answer "Jawaban resmi..."

# 直接教一条（不必先有 unknown）
python scripts/teach_kb.py --question "..." --answer "..." --lang id
```

生产示例：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec worker \
  python scripts/list_unknown_questions.py
```

## Agent 检索顺序

1. 强匹配 `history_pairs` → 模仿人工口吻  
2. FAQ（`faq.json`，含 Excel V2 + 旧库去重 + 教答）  
3. 弱检索 + LLM（若有 key）  
4. 否则 handoff，并记入 unknown

学习质量 OK、确认可对客后再设 `AI_SEND_TO_CUSTOMER=true`。
