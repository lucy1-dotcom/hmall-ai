# hmall 后端（Java 微服务）

## 模块

| 模块 | 端口 | 说明 |
|---|---|---|
| hm-gateway | 8080 | 网关：路由、JWT 鉴权、AI 对话转发（`lb://hmall-ai`） |
| item-service | 8081 | 商品 |
| cart-service | 8082 | 购物车 |
| user-service | 8084 | 用户、地址、余额 |
| trade-service | 8085 | 订单 |
| pay-service | 8086 | 支付 |
| hm-common / hm-api | - | 公共依赖 / Feign 客户端 |
| hm-service | 8083 | 早期的单体服务（拆分前的原型，保留作对照） |

## 配置中心（Nacos Config）

5 个业务服务的**数据库配置、MyBatis-Plus 全局策略、日志格式**已经从本地 yaml
移到了 Nacos，本地只保留端口、profile、knife4j 文档配置这类“服务自身形态”的内容。

```
Nacos 控制台 → 配置管理 → 配置列表
  hmall-common.yaml     公共配置（所有服务共享）
  item-service.yaml     item-service 专属（datasource + hm.demo 演示项）
  cart-service.yaml     ...
  user-service.yaml
  trade-service.yaml
  pay-service.yaml
```

### 加载顺序

`bootstrap.yaml`（每个服务一份）在 bootstrap 阶段执行，这里才放得了配置中心地址：

```yaml
spring:
  application:
    name: item-service
  cloud:
    nacos:
      config:
        server-addr: 192.168.150.131:8848
        file-extension: yaml
        shared-configs:
          - data-id: hmall-common.yaml
            refresh: true
```

> Spring Boot 2.4+ 默认关闭 bootstrap，必须引入 `spring-cloud-starter-bootstrap`
> 依赖才发现 `bootstrap.yaml`，否则配置中心只加载 `application.yaml` 里写的东西。

### 热更新演示

`item-service` 里有一个 `@RefreshScope` 的演示接口：

```
GET http://localhost:8081/config/demo
→ {"message":"config-center-v1","limit":10,...}
```

在 Nacos 改 `item-service.yaml` 的 `hm.demo.message`，**不用重启**，
约 3 秒后再请求就变成新值（Nacos 客户端长轮询推送 → `RefreshScope` 重建 Bean → `@Value` 重新注入）。

### 本地/线上差异

- 数据库地址仍是 `${hm.db.host}` / `${hm.db.pw}`，值放在 `application-local.yaml`
  （本机跑）或 `application-dev.yaml`（Docker 里跑）。**密码不进配置中心**。
- 启动时用 `--spring.profiles.active=local` 指向本机。

## 踩坑记录

1. **Nacos 存中文会坏**：用 HTTP API 发布配置时，如果不带
   `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`，
   Tomcat 按 ISO-8859-1 解码，存进去的字节不是合法 UTF-8，Java 端 YAML 解析直接
   `MalformedInputException`。**配置内容统一用 ASCII 注释**，需要中文时务必带 charset 头。
2. **JDK 17 默认字符集是 GBK**：即使存的是正确 UTF-8，客户端用平台编码解码也会坏。
   确需在配置里写中文，启动加 `-Dfile.encoding=UTF-8`（JDK 18+ 默认 UTF-8 无此问题）。
3. **YAML 拼接少一个换行就全崩**：脚本拼配置内容时，`3000` 和下一行 `hm:` 连成了
   `3000hm:`，报 `mapping values are not allowed here`——发布后一定回读校验。

## 流量防护（Sentinel）

| 服务 | 资源 | 规则 | 兜底 |
|---|---|---|---|
| item-service | `queryItemById` | QPS ≤ 2 | `blockHandler` 返回 429 |
| trade-service | `createOrder` | 异常比例 > 50% 熔断 10s | `fallback` 返回 503 |

规则由 `SentinelRuleConfig` 用代码加载（`FlowRuleManager` / `DegradeRuleManager`），
不依赖 dashboard 是否启动，项目开箱即跑。

实测：

```
突发 8 次 /items/2120808
→ 200, 200, 200, 429, 429, 429, 429, 429
→ {"code":429,"msg":"请求过于频繁，请稍后再试","data":null}

停掉 item-service 后下单
→ HTTP 503 {"code":503,"msg":"订单服务暂时不可用，请稍后重试"}
→ 日志：createOrderFallback 被调用
```

`fallback` 只兜下游故障；业务异常通过 `exceptionsToIgnore = CommonException.class` 排除，
否则「库存不足」这种正常业务失败也会被记进熔断指标，把熔断器误打开。

### Dashboard（可选）

```bash
# Maven 中央仓库没有这个包，只能从 GitHub Release 下
# https://github.com/alibaba/Sentinel/releases/download/1.8.6/sentinel-dashboard-1.8.6.jar
java -jar sentinel-dashboard-1.8.6.jar --server.port=8858
# http://localhost:8858  默认 sentinel / sentinel
```

服务里已配 `spring.cloud.sentinel.transport.dashboard=localhost:8858`，
dashboard 起来后十几秒就能在左边看到 item-service / trade-service。
没起 dashboard 时只会每 10 秒打一条连接失败 WARN，规则照常生效。

## 顺手修的一个坑

`hm-common` 的 `CommonExceptionAdvice`（统一异常处理）原来**没有注册进 `spring.factories`**，
导致微服务里的业务异常全部变成 Spring 默认的 500 JSON——只有单体 `hm-service`
因为包扫描顺带生效了。现已加进自动配置，并加上
`@ConditionalOnWebApplication(SERVLET)`：网关是 WebFlux，不能注册基于 Servlet 的 advice。

## 商品语义搜索（Milvus 向量检索）

关键词搜索走的是 `LIKE '%关键字%'`，用不上索引，而且**字面匹配不到就返回 0 条**。
这里把商品向量化后做语义检索，解决"搜『降噪耳机』但商品名里没有『降噪』"这类问题。

```
离线：item-service /items/page 分页拉商品
      → 拼「名称 + 品牌 + 类目 + 规格」
      → bge-m3 向量化（1024 维）
      → 写入 Milvus 集合 hmall_items

在线：/api/ai/search → 查询向量化 → ANN 检索 top-k → 返回商品卡片（价格/图片/类目）
```

| 组件 | 位置 |
|---|---|
| 离线入库 | `hmall-ai/ingest_items.py`（`--limit` / `--start-page` 断点续传 / `--drop` 重建） |
| 向量库封装 | `hmall-ai/app/crud/milvus.py`、`app/services/vector_store.py` |
| 查询缓存 | `VectorStoreService.query_vector`：热门搜索词只算一次 embedding |
| 接口 | `POST /ai/search`，经网关 `POST /api/ai/search` 对外 |
| 压测脚本 | `perf/search_bench.py`（关键词 vs 语义，同一入口对比） |

### 实测（83,674 条商品已入库）

**召回能力**（三个自然语言查询，关键词全部 0 命中）：

| 查询 | 关键词 LIKE | 语义搜索 |
|---|---|---|
| 降噪耳机 | **0 条** | 10 条（华为耳机 / 蓝牙对耳） |
| 适合打游戏的手机 | **0 条** | 10 条（荣耀 10 GT 游戏加速手机，score 0.67） |
| 送女朋友的礼物 | **0 条** | 10 条（女士钱包 / 手拿包） |

**延迟**（经网关同一入口，单条请求，30 次取分位）：

| 方案 | avg | p50 | p95 | p99 |
|---|---|---|---|---|
| 关键词搜索（MySQL LIKE） | 97.4ms | 97.7ms | 110.9ms | 113.1ms |
| 语义搜索（缓存命中） | **6.0ms** | 5.4ms | 8.5ms | 19.2ms |
| 语义搜索（缓存未命中） | 337ms | 323ms | 408ms | 519ms |

> 语义搜索的耗时几乎全在 embedding 接口的网络往返（约 300ms），
> Milvus 检索本身只要几毫秒。所以给查询向量加了进程内缓存：
> 热门词重复命中后从 337ms 降到 6ms，比 LIKE 快 16 倍。

### 怎么跑

```bash
cd back/hmall-ai
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 1) 建索引（item-service 已启动）
.venv\Scripts\python.exe ingest_items.py --limit 20000   # 先灌 2 万条试水
.venv\Scripts\python.exe ingest_items.py                 # 全量 8.8 万条，约 25 分钟
.venv\Scripts\python.exe ingest_items.py --start-page 428  # 中断后续传

# 2) 起服务（必须监听 0.0.0.0，否则网关连不上注册的局域网 IP）
.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000

# 3) 对比压测
python perf/search_bench.py --keyword-url http://127.0.0.1:8080/search/list \
                            --vector-url http://127.0.0.1:8080/api/ai/search
```

**踩过的坑**：
- 入库时个别商品文本会让 embedding 接口返回 400，整页失败会中断整个任务
  → 加了「批量失败则逐条重试、跳过坏数据」的兜底。
- 先灌 2 万条时发现按 id 排序漏掉了整个类目（搜"降噪耳机"返回行李箱），
  → 说明**向量检索的效果非常依赖索引覆盖度**，必须全量入库。

## 压测数据（JMeter）

脚本：[`perf/hmall-load-test.jmx`](perf/hmall-load-test.jmx)（参数化，可覆盖 host/port/threads/loops）

```bash
jmeter -n -t perf/hmall-load-test.jmx -l perf/results/result.jtl -e -o perf/results/html
jmeter -n -t perf/hmall-load-test.jmx -l perf/results/high.jtl -Jthreads=50 -Jloops=10
```

压测目标：网关（8080）→ item-service（8081）→ MySQL（虚拟机）。

### 四组对比

| 场景 | 请求数 | 耗时 | 吞吐 | 平均 | P95 | P99 | 最大 | 错误率 |
|---|---|---|---|---|---|---|---|---|
| 经网关 20 并发 | 1200 | 13.3s | **90.4/s** | 149.6ms | 427ms | 521ms | 649ms | 0% |
| 直连服务 20 并发 | 1200 | 12.3s | **97.4/s** | 132.5ms | 386ms | 476ms | 585ms | 0% |
| 经网关 50 并发 | 1500 | 15.4s | **97.6/s** | 346.5ms | 704ms | 866ms | 1151ms | 0% |
| 经网关 50 并发·连接池 30 | 1500 | 17.5s | **85.6/s** | 458.7ms | 1292ms | 1534ms | 1898ms | 0% |

### 分组数据（经网关 20 并发，按接口）

| 接口 | 请求数 | 平均 | P50 | P95 | P99 | 最大 |
|---|---|---|---|---|---|---|
| 商品详情（主键查询 `/items/{id}`） | 400 | 57.4ms | 44ms | 159ms | 205ms | 311ms |
| 商品分页（`/items/page`） | 400 | 76.8ms | 64.5ms | 171ms | 211ms | 230ms |
| 关键词搜索（`/search/list?key=手机`） | 400 | **314.8ms** | 316ms | 503ms | 594ms | 649ms |

### 结论

1. **网关开销可控**：同样 20 并发，经网关 90.4/s vs 直连 97.4/s，吞吐差约 7%，平均延迟多约 17ms——这是路由匹配 + JWT 过滤 + 负载均衡换来的，可以接受。
2. **50 并发吞吐没涨、延迟翻倍**：97.6/s 与 20 并发基本相同，但 P99 从 476ms 升到 866ms → 系统已经在 ~97 req/s 饱和，瓶颈不在网关。
3. **连接池 10 → 30 后反而更差**：吞吐 85.6/s、P99 1534ms。这是本次压测最有价值的发现——**瓶颈不在连接池**，盲目加连接只会加剧数据库侧竞争。真正的瓶颈是数据库单机能力 + 压测机到虚拟机的网络往返。
4. **关键词搜索是全链路最慢的接口**：平均 314.8ms，是主键查询的 **5.5 倍**，因为 `name LIKE '%手机%'` 用不上索引，8.8 万行全表扫描。

> 由此得到的优化方向：商品详情上 Redis 缓存（读多写少、命中率高），搜索上 ES（倒排索引替代 LIKE），
> 而不是继续调连接池这种"看起来能调"的参数。

## 订单超时关闭（RabbitMQ 延迟消息）

下单后如果用户一直不付款，订单会一直占着库存。这里用 RabbitMQ 的
**延迟消息插件**（`rabbitmq_delayed_message_exchange`）实现自动关单。

```
下单成功 → 投递延迟消息(x-delay=10s) → 到期投递到队列 → 消费者检查订单状态
                                                       ├─ 未支付：status 1→5，回补库存
                                                       └─ 已支付/已关闭：跳过
```

| 组件 | 位置 |
|---|---|
| 交换机/队列/绑定 | `trade-service/.../config/OrderMqConfig.java`（`x-delayed-message` 交换机） |
| 生产者 | `mq/OrderTimeoutProducer.java`，下单事务提交后投递 |
| 消费者 | `mq/OrderTimeoutListener.java`，`@RabbitListener` |
| 关单逻辑 | `OrderServiceImpl#closeUnpaidOrder` |
| 库存回补 | item-service 新增 `PUT /items/stock/restore`，`hm-api` 的 `ItemClient` 同步加方法 |

**为什么不用 TTL + 死信队列**：同一个队列里不同 TTL 的消息会**队头阻塞**
（先到的长 TTL 消息没到期，后面短 TTL 的也出不来），必须按 TTL 拆多个队列，
维护成本高。延迟插件是消息级别的定时，语义直接。

**幂等怎么保证**：`closeUnpaidOrder` 用条件更新
`UPDATE order SET status=5 WHERE id=? AND status=1`，只有更新成功的那一次才回补库存。
所以消息重复投递、或用户恰好在同一刻支付，都不会重复回补库存、也不会误关已支付订单。

### 实测

```
下单前库存 996
下单(num=2) → 订单 2118684590041804801 status=1，库存 994
20:39:04.924  订单超时消息已投递 orderId=... delay=10000ms
20:39:14.219  收到订单超时消息（延迟 9.3 秒，符合预期）
20:39:14.316  订单超时处理完成 → 已关闭并回补库存
13 秒后复查：status=5、closeTime 有值、库存回到 996

手动重复投递同一条消息（管理台 API）：
  → 消费者再次消费，但库存仍 996（没有变成 998），状态仍为 5 —— 幂等生效
```

### 配置

`trade-service.yaml`（Nacos）：

```yaml
spring.rabbitmq:
  host: 192.168.150.131
  port: 5672
  username: itheima
  password: 123321
  listener.simple.default-requeue-rejected: false   # 失败不要无限重回队列
  listener.simple.retry.max-attempts: 3
hm.order.timeout-ms: 10000    # 演示 10 秒；生产 1800000（30 分钟）
```

> 改 `hm.order.timeout-ms` 需要重启 trade-service 才生效（`@Value` 注入，没加 `@RefreshScope`）。

## 启动顺序

```
MySQL/Nacos（虚拟机）→ 各业务服务 → 网关
```

服务启动日志里出现这一行说明配置中心生效：

```
Located property source: [BootstrapPropertySource {name='bootstrapProperties-item-service.yaml,DEFAULT_GROUP'}, ...]
```
