"""数据访问层（CRUD）。

面向两处数据源：
1. 向量库 Milvus —— 商品知识、问答知识库的向量化存储（见 milvus.py）
2. 业务数据（MySQL）—— 如果 AI 服务需要直接读商品/订单表，可以在这里扩
   一个 sqlalchemy 的 Repository；默认不直连，统一走网关调 Java 服务，
   避免绕过微服务的边界。
"""
