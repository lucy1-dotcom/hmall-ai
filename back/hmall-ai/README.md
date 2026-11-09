# hmall-ai

黑马商城（hmall）的 **AI 微服务**，Python + FastAPI 实现，和 `cart-service`、`item-service` 等
Java 服务并列放在 `back/` 下，由 Nginx 上的静态前端通过 HTTP 直接调用（跨域，已配置 CORS）。

## 目录结构

```
hmall-ai/
├── main.py                     # 入口：app = create_app()，uvicorn main:app
├── ingest.py                   # 离线脚本：policy.txt -> 切块 -> bge-m3 -> Milvus
├── policy.txt                  # 商城退换货政策原文（知识库语料）
├── requirements.txt            # 依赖
├── .env.example                # 环境变量样例（复制成 .env 使用）
├── Dockerfile                  # 镜像构建
├── app/
│   ├── application.py          # 应用工厂：CORS、异常处理、路由装配、lifespan
│   ├── core/                   # 基础设施
│   │   ├── config.py           # pydantic-settings 配置（环境变量 -> Settings）
│   │   ├── logging.py          # 控制台 + 滚动文件日志
│   │   ├── exceptions.py       # 统一异常与错误响应
│   │   └── deps.py             # 依赖注入（配置、用户身份占位）
│   ├── routers/                # 接口层（按业务拆分）
│   │   ├── health.py           # /ai/health、/ai/ping
│   │   ├── chat.py             # /ai/chat        智能客服（RAG）
│   │   ├── search.py           # /ai/search      自然语言搜索
│   │   ├── knowledge.py        # /ai/knowledge/ingest 知识入库
│   │   └── agent.py            # /api/ai/chat    订单 Agent（注意：不带 /ai 前缀）
│   ├── agents/                 # LangChain Agent
│   │   └── order_agent.py      # ChatOpenAI(DeepSeek) + 工具装配 + run_agent
│   ├── tools/                  # Agent 可调用的工具
│   │   ├── order.py            # get_order_status（httpx 异步调 Java 接口）
│   │   └── policy.py           # search_policy（检索 Milvus 政策知识库）
│   ├── services/               # 业务层
│   │   ├── llm.py              # LangChain ChatModel 封装 + 演示模式
│   │   ├── embeddings.py       # 硅基流动 bge-m3 向量化
│   │   ├── policy.py           # 政策检索
│   │   ├── vector_store.py     # 商品向量检索
│   │   └── item_client.py      # 经网关调用 Java 商品服务
│   ├── models/                 # Pydantic 模型（请求/响应）
│   │   ├── common.py           # 统一响应、健康检查
│   │   ├── chat.py             # 对话
│   │   ├── agent.py            # Agent 请求/响应
│   │   └── search.py           # 检索
│   ├── crud/                   # 数据访问层
│   │   └── milvus.py           # Milvus 向量库增删改查（延迟导入 pymilvus）
│   ├── services/               # 业务层
│   │   ├── llm.py              # LangChain ChatModel 封装 + 演示模式
│   │   ├── embeddings.py       # 硅基流动 bge-m3 向量化
│   │   ├── policy.py           # 政策检索
│   │   ├── vector_store.py     # embedding + 语义检索 + 切块入库
│   │   └── item_client.py      # 经网关调用 Java 商品服务
│   ├── utils/
│   │   └── text.py             # 分块、截断、上下文拼接
│   └── __init__.py
└── tests/
    └── test_health.py          # 健康检查 / CORS 预检 / 参数校验
```

## 快速开始

```bash
cd back/hmall-ai

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

copy .env.example .env

# 把政策知识库灌进 Milvus（需要先启动 Milvus，并配好 SILICONFLOW_API_KEY）
python ingest.py

uvicorn main:app --reload --port 8000
# 或者
python main.py
```

打开：

- 接口文档 <http://127.0.0.1:8000/docs>
- 健康检查 <http://127.0.0.1:8000/ai/health>

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ai/health` | 健康检查（报告 LLM / Milvus / 网关的配置状态，不发起外部调用） |
| GET | `/ai/ping` | 轻量探活 |
| POST | `/ai/chat` | 智能客服：向量检索 + 大模型回答，返回引用来源 |
| POST | `/ai/search` | 自然语言搜索商品；向量库不可用时降级为关键词搜索 |
| POST | `/ai/knowledge/ingest` | 把商品文档切块向量化写入 Milvus |
| POST | `/api/ai/chat` | **订单 Agent（SSE 流式）**：边生成边推，前端可做打字机效果 |
| POST | `/api/ai/chat/sync` | 同一个 Agent 的非流式版本，返回一次性 JSON，便于调试 |

> `/api/ai/chat` 的路径是需求指定的，不带全局 `/ai` 前缀，所以在 `application.py`
> 里是单独 `include_router`、不传 prefix 的，别把它和 `/ai/chat` 搞混。
>
> **前端不直连这两个接口**，而是调 Java 网关的 `POST /api/chat/send`，
> 由 `hm-gateway` 里的 `AiChatController` 用 WebClient 转发（见「和前端 / Java 网关对接」）。

调用示例：

```bash
curl -X POST http://127.0.0.1:8000/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"这款手机的保修期多久？","item_id":"2120808"}'

curl -X POST http://127.0.0.1:8000/ai/search \
  -H "Content-Type: application/json" \
  -d '{"query":"适合打游戏的手机","top_k":5}'
```

## 订单 Agent（LangChain）

一个能自己决定「要不要查数据库」的 Agent：用户问订单，它调工具；问别的，它直接答。

```
POST /api/ai/chat
{
  "user_id": 1,
  "message": "我的订单到哪了？"
}

→ 200
{
  "code": 200,
  "message": "success",
  "data": {
    "reply": "您最近一笔订单已支付，正在等待发货。",
    "session_id": "2f2d7476661144528f1322664e8bba69",
    "model": "deepseek-chat",
    "tools_used": ["get_order_status"]
  }
}
```

组成：

| 部件 | 位置 | 作用 |
|---|---|---|
| Tool `get_order_status` | `app/tools/order.py` | `httpx.AsyncClient` 异步请求 `{HMALL_GATEWAY_URL}/api/order/latest?userId=...`，把结果转成 JSON 字符串回给模型 |
| LLM | `app/agents/order_agent.py` | `ChatOpenAI` + `base_url=deepseek`，DeepSeek 兼容 OpenAI 协议 |
| Agent | 同上 | `create_agent(model, tools, system_prompt)`，系统提示里带上当前 `user_id` |
| 路由 | `app/routers/agent.py` | `POST /api/ai/chat`，出参统一 `{code, message, data}` |

配置一个环境变量就能用真模型（全项目统一，不再区分 OpenAI / DeepSeek）：

```bash
LLM_API_KEY=sk-xxxx
LLM_BASE_URL=https://api.deepseek.com/v1   # 默认值，换厂商才需要改
LLM_MODEL=deepseek-chat
```

> 老变量名 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` 仍然兼容：启动时会自动收敛到
> `llm_api_key`，老 `.env` 不用改。但新配置建议统一用 `LLM_*`。

没配 `LLM_API_KEY` 时接口返回 **503** 且提示明确，不会抛 500 堆栈。

## 流式输出与会话记忆

### 记忆（SQLite 持久化）

用的是 LangGraph 的 `AsyncSqliteSaver`，按 `thread_id` 存会话状态，
`thread_id` 直接复用前端的 `session_id`：

```python
# app/core/memory.py
db_path = Path(settings.memory_db_path)          # 默认 data/memory.db
saver = await AsyncSqliteSaver.from_conn_string(str(db_path))
await saver.setup()                               # 建表（幂等）

# app/agents/order_agent.py
create_agent(model=llm, tools=AGENT_TOOLS,
             system_prompt=..., checkpointer=memory_store.saver)
config = {"configurable": {"thread_id": session_id}}
```

- 同一个 `session_id` → 接着上一轮聊；换一个 → 全新会话。
- **落盘**：服务重启后会话还在（实测重启后问「刚才我说我叫什么」，仍答「你叫小明」）。
- `MEMORY_BACKEND=memory` 可切回进程内模式，跑测试时用这个，不产生文件。
- 裁剪：历史超过 **10 条**时只保留最近 10 条。切点会向后对齐到最近的用户消息，
  避免把「tool_calls 有、tool 结果丢了」这种半轮切出来（那样模型接口会直接报错）。

实测（同一 session 连问 7 轮，模型侧看到的消息数）：

```
第1轮 2 条 / 第2轮 4 条 / 第3轮 6 条 / 第4轮 8 条 / 第5轮 10 条
第6轮 12 条（触发裁剪：10 条历史 + 新问题 + system）
第7轮 12 条（稳定）
换 session_id → 回到 2 条
```

### 流式（SSE）

`POST /api/ai/chat` 返回 `text/event-stream`，事件如下：

| type | 含义 | 字段 |
|---|---|---|
| `meta` | 流开始 | `session_id`、`model` |
| `tool` | 模型决定调用工具 | `name` |
| `token` | 文本增量 | `content` |
| `done` | 正常结束 | `session_id` |
| `error` | 流中途出错 | `message` |

原始报文长这样（`\n\n` 分隔事件）：

```
data: {"type": "meta", "session_id": "sse-demo", "model": "deepseek-chat"}

data: {"type": "tool", "name": "search_policy"}

data: {"type": "token", "content": "根"}

data: {"type": "token", "content": "据"}

data: {"type": "done", "session_id": "sse-demo"}
```

**为什么不用 `EventSource`**：它只支持 GET，而我们要 POST 一个 JSON body。
所以用 `fetch` + `ReadableStream` 手动按 `\n\n` 切事件（见下面的 JS）。

### 前端接收（原生 JS）

```js
let sessionId = localStorage.getItem('hmall_ai_session') || null;

async function chat(message, onToken) {
  // 走 Java 网关，前端不直连 Python（Nginx 会把 /api 剥掉转给 8080）
  const res = await fetch('/api/chat/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: 1, message, session_id: sessionId })
  });

  // 参数错误 / 没配密钥会在这里返回普通 JSON
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });   // 防止汉字被截断成乱码

    let sep;
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const rawEvent = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      for (const line of rawEvent.split('\n')) {
        if (!line.startsWith('data:')) continue;
        const payload = JSON.parse(line.slice(5).trim());

        if (payload.type === 'meta') sessionId = payload.session_id;
        else if (payload.type === 'token') onToken(payload.content);   // 追加到气泡
        else if (payload.type === 'tool') console.log('调用工具', payload.name);
        else if (payload.type === 'error') throw new Error(payload.message);
        else if (payload.type === 'done') return;
      }
    }
  }
}
```

仓库里有一个可直接打开的完整演示页：
`front/html/hmall-portal/ai-chat-demo.html` → <http://localhost:18080/ai-chat-demo.html>
（含光标闪烁、工具调用提示、session 持久化，不需要 Vue）。

### 部署注意

**前端不要直连 Python 端口。** 正确链路是：

```
浏览器 → Nginx(18080) /api/chat/send → 网关 8080 → AiChatController → Python 8000
```

Nginx 这边只需要保证 `/api` 这一段**不缓冲**（前端其余请求同样走 `/api`，所以这段配置对所有接口都适用）：

```nginx
location /api {
    rewrite /api/(.*)  /$1 break;
    proxy_pass http://localhost:8080;

    # SSE 流式转发关键配置：不关缓冲的话，Nginx 会把整个流攒完再一次性发
    proxy_buffering off;
    proxy_cache off;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    chunked_transfer_encoding off;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

- 服务端已经带了 `X-Accel-Buffering: no` 响应头，Nginx 会据此不缓冲；
  但如果你在中间又套了一层网关/压缩，仍需确认没有累积。
- `Content-Encoding: gzip` 对 SSE 是灾难，别在这一层开压缩。
- Java 侧（WebClient）也不能设「响应体读超时」，否则长回答会被掐断；
  网关的 `hm.ai.response-timeout-seconds` 默认 180 秒，指两次数据之间的最大间隔。

## 售后政策 RAG（Milvus + bge-m3）

```
policy.txt ──切块(500字/重叠50)──> bge-m3 向量化 ──> Milvus(hmall_policy)
                                                          │
用户问「拆封的手机能退吗」 ──> Agent 判断 ──> search_policy 工具 ──> 检索 Top3 条款
                                                          │
                                        模型依据条款总结回答（点明依据第几条）
```

**1. 入库**

```bash
# 配好 key（脚本读环境变量，不写死）
set SILICONFLOW_API_KEY=sk-xxxx

python ingest.py
# 可选参数
python ingest.py --file policy.txt --chunk-size 500 --overlap 50
python ingest.py --drop        # 改了切块参数时，先删集合重建
```

输出示例：

```
文件：policy.txt（1256 字）
切块：chunk_size=500 overlap=50 -> 3 块
  第1块预览（480 字）：黑马商城（hmall）售后服务与退换货政策 第一条 适用范围 …
向量化：模型 BAAI/bge-m3，接口 https://api.siliconflow.cn/v1
向量维度：1024
[完成] 写入 3 条向量到集合 hmall_policy
```

`id` 取文本的 md5，重复执行是幂等的（同内容覆盖，不产生重复行）。

**2. 检索工具**：`app/tools/policy.py` 的 `search_policy(query)`，
向量化问题 → 查 Milvus Top3 → 把条款拼成文本返回给模型。

**3. Agent 规则**：系统提示里明确「售后政策问题必须先调 `search_policy`，
依据条款回答并点明第几条，查不到就如实说没有相关规定」。

**4. 配置项**

| 变量 | 说明 | 默认 |
|---|---|---|
| `MILVUS_URI` | Milvus 地址 | `http://localhost:19530` |
| `SILICONFLOW_API_KEY` | 硅基流动密钥（没有它工具会明确提示未配置） | 空 |
| `SILICONFLOW_BASE_URL` | 硅基流动网关 | `https://api.siliconflow.cn/v1` |
| `POLICY_EMBEDDING_MODEL` | 向量模型 | `BAAI/bge-m3` |
| `POLICY_COLLECTION` | 集合名 | `hmall_policy` |
| `POLICY_TOP_K` | 检索条数 | `3` |

> 需求里给的 Milvus 地址是 `192.168.150.128:19530`，实测**不可达**（虚拟机能通的是
> `192.168.150.131`，且上面没有 Milvus）。实际 Milvus 跑在本机 Docker
> （容器 `milvus-standalone`，版本 v3.0.5），所以默认值用 `http://localhost:19530`。
> 真要连远端，改 `MILVUS_URI` 一个变量即可，代码不用动。

**5. 没有硅基流动 key 时怎么验证**

`tests/mock_embedding.py` 用字符 bigram 哈希模拟 1024 维向量，
能把「切块 → 向量 → Milvus → 检索」整条链路跑通（没有语义能力，只有字面相似）：

```bash
python tests/mock_embedding.py 8097
set SILICONFLOW_BASE_URL=http://127.0.0.1:8097/v1
set SILICONFLOW_API_KEY=test
python ingest.py --drop
```

> 它只是个手动启动的本地 HTTP 服务，文件名不以 `test_` 开头，pytest 不会收集。
> 配好真实 key 之后就用不到它了。

**实测**（本机 Milvus v3.0.5，3 块政策文本）：

```
查询「拆封的手机能退吗」→ 命中 3 条，Top1 含「手机…一经拆封或激活，非质量问题不支持七天无理由退货」
查询「发票怎么开」      → Top1 含第八条发票条款
```

Agent 侧日志：

```
app.services.policy - 政策检索 query='拆封的手机能退吗？' 命中 3 条
app.crud.milvus - 已连接 Milvus: http://localhost:19530
POST /api/ai/chat 200  {"tools_used":["search_policy"]}
```

**踩坑记录**：Milvus 3.x 起，`VARCHAR` 主键必须显式传 `max_length`，否则建集合报
`type param(max_length) should be specified for the field(id)`——`app/crud/milvus.py`
里已经补上 `max_length=64`。

## 和 Java 服务的对接

Agent 的订单数据来自 `trade-service` 新增的接口：

```java
@RestController
@RequestMapping("/api/order")
public class OrderAgentController {
    @GetMapping("/latest")
    public Map<String, Object> queryLatestOrder(@RequestParam("userId") Long userId) { ... }
}
```

返回：

```json
{"orderId":"2083071012068392962","status":"已支付，待发货","statusCode":2,"totalFee":75500,"createTime":"2026-07-31T14:03:25"}
```

没有订单时返回 `{"orderId": null, "status": "暂无订单"}`（HTTP 仍为 200，方便工具判断）。

网关 `hm-gateway/src/main/resources/application.yaml` 里补了两处：

```yaml
routes:
  - id: trade-api
    uri: lb://trade-service
    predicates:
      - Path=/api/order/**
hm:
  auth:
    excludePaths:
      - /api/order/**     # AI 服务内部调用，userId 由调用方显式传入
```

> 注意：把 `/api/order/**` 加入 `excludePaths` 意味着这条路径**不再校验 JWT**。
> 生产环境更稳妥的做法是让 AI 服务携带服务令牌，或把该接口收到内网。

## 设计要点

**1. 重依赖延迟导入**
`pymilvus`、`langchain_openai` 都在真正用到时才 import（见 `crud/milvus.py`、`services/llm.py`）。
好处是：没装 Milvus 客户端、没配大模型密钥，服务照样能启动，`/ai/health`、`/ai/search`
（降级走关键词）都能用，方便先联调前端。

**2. 不可用就降级，而不是 500**

- 没配 `OPENAI_API_KEY` → 演示模式，返回固定话术，`degraded=true`
- Milvus 连不上 → `/ai/search` 自动改调网关的 `/search/list`（关键词搜索），`degraded=true`
- 都失败 → 返回空结果 + 提示，不抛 500

**3. 不绕过微服务边界**
AI 服务不直连 MySQL，统一通过网关 `http://localhost:8080` 调 Java 服务，
这样网关上的路由、鉴权、限流对 AI 服务同样生效。

**4. CORS**
`CORS_ORIGINS` 默认放行 18080/18081/18082。如果配成 `*`，
`application.py` 会自动把 `allow_credentials` 降为 `false`——浏览器规范不允许
`allow_origins=["*"]` 与凭证同时开启，否则预检直接失败。

## 和前端 / Java 网关对接

**前端只认 Java，不直连 Python 端口。** 链路：

```
浏览器 ──/api/chat/send──> Nginx(18080) ──/chat/send──> 网关(8080) ──POST /api/ai/chat──> Python(8000)
        <────────────── SSE 事件逐帧回传（三层都不缓冲）──────────────
```

Java 侧在 `hm-gateway` 里新增了 `AiChatController`：

```java
@PostMapping(value = {"/chat/send", "/api/chat/send"}, produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public Flux<ServerSentEvent<String>> send(@Valid @RequestBody AiChatRequest request) {
    return aiWebClient.post()
            .uri("/api/ai/chat")
            .contentType(MediaType.APPLICATION_JSON)
            .accept(MediaType.TEXT_EVENT_STREAM)
            .bodyValue(request)
            .retrieve()
            .onStatus(HttpStatus::isError, resp -> /* 转成 AiChatException */)
            .bodyToFlux(SSE_TYPE)          // 逐帧解码，天然保持流式
            .onErrorResume(this::toErrorEvent);
}
```

- 两个映射：Nginx 的 `location /api` 会剥掉 `/api`，到网关是 `/chat/send`；
  直连网关时是 `/api/chat/send`。两种都支持。
- `WebClient` 只设连接超时，不设「响应体读超时」，否则长回答会被掐断。
- Python 返回 4xx/5xx（参数错、没配密钥）时，网关把它转成一条
  `{"type":"error","message":...}` 事件——因为流已经开始，HTTP 状态码改不了了。
- 网关配置：`hm.ai.service-url`（默认 `http://hmall-ai`，走 Nacos 服务发现）；
  `/chat/**` 已加入 `hm.auth.excludePaths`，不走 JWT。

## 服务注册（Nacos）

`NACOS_ENABLED=true` 时，服务启动会在 lifespan 里注册自己，关闭时注销：

```python
# app/core/nacos.py
client = NacosClient(settings.nacos_server_addr, namespace=..., username=..., password=...)
client.add_naming_instance(
    "hmall-ai", ip, port,
    group_name="DEFAULT_GROUP", cluster_name="DEFAULT",
    ephemeral=True, heartbeat_interval=5,          # 临时实例，SDK 自动心跳
)
```

- 注册的 IP 默认探测本机出口网卡，多网卡/容器里用 `NACOS_REGISTER_IP` 显式指定。
- 注册失败只打日志，服务照样能用（网关也可以退回直连）。
- 网关侧 `hm.ai.service-url: http://hmall-ai` + `@LoadBalanced WebClient`，
  所以换机器、换端口、多实例扩容都不用改网关配置。

实测（Nacos 2.1.0）：

```
instance: 192.168.1.32:8000  healthy=true  ephemeral=true
全链路：Nginx(18080) → 网关(8080, lb) → Python(8000) → DeepSeek，逐 token 流式
```

## 后续可以接的东西

- **知识初始化**：从 `item-service` 拉商品，批量调 `/ai/knowledge/ingest` 建库。
- **限流与鉴权**：AI 对话接口目前走网关白名单；要按用户限流的话，
  在 `AiChatController` 里解析 JWT 拿 userId，再做频次控制。
- **多实例记忆**：SQLite 是单机文件，多副本部署时要换 Postgres/Redis 版 checkpointer。
- **可观测性**：接 OpenTelemetry，把 Agent 的 token 消耗、工具耗时打点。
