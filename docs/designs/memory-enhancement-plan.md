# Agent Zero 记忆系统增强开发计划

> **版本**: 1.0  
> **创建日期**: 2026-01-30  
> **目标**: 将 OpenClaw 的先进记忆管理技术移植到 Agent Zero，提升其记忆检索质量和会话管理能力

---

## 📋 目录

- [1. 项目概述](#1-项目概述)
- [2. 技术对比分析](#2-技术对比分析)
- [3. 整体架构设计](#3-整体架构设计)
- [4. 分阶段实施计划](#4-分阶段实施计划)
- [5. 模块详细设计](#5-模块详细设计)
- [6. 测试与验收标准](#6-测试与验收标准)
- [7. 风险评估与缓解](#7-风险评估与缓解)
- [8. 后续优化方向](#8-后续优化方向)

---

## 1. 项目概述

### 1.1 背景

Agent Zero 是一个通用型自主 AI 代理框架，具有强大的代码执行和多代理协作能力。OpenClaw 是一个多渠道 AI 助手平台，在记忆管理和检索方面有独特的技术优势。

本项目旨在将 OpenClaw 在记忆系统方面的技术优势移植到 Agent Zero，同时保留 Agent Zero 现有的智能记忆合并 (Memory Consolidation) 功能。

### 1.2 项目目标

| 目标 | 描述 | 优先级 |
|------|------|--------|
| 混合检索 | 实现向量 + 关键词混合检索，提升召回率 | ⭐⭐⭐⭐⭐ |
| 会话持久化 | 支持会话历史的持久化存储和语义检索 | ⭐⭐⭐⭐ |
| 实时索引 | 文件监控，知识变更自动触发索引更新 | ⭐⭐⭐ |
| Embedding 缓存 | 减少重复 Embedding 计算，降低 API 成本 | ⭐⭐⭐⭐ |
| 增量同步 | 基于 Hash 的增量同步，减少不必要的重新索引 | ⭐⭐⭐⭐ |

### 1.3 预期收益

```
┌─────────────────────────────────────────────────────────┐
│                    预期效果对比                          │
├─────────────────┬─────────────┬─────────────────────────┤
│      能力        │   改造前    │        改造后           │
├─────────────────┼─────────────┼─────────────────────────┤
│ 检索质量        │  纯语义 70%  │ 混合检索 90%+          │
│ 精确匹配        │  ❌ 不支持   │ ✅ FTS5 全文搜索       │
│ 会话检索        │  ❌ 无       │ ✅ 语义搜索历史会话    │
│ 索引更新        │  启动时预加载│ ✅ 实时文件监控        │
│ API 成本        │  每次计算    │ ✅ 缓存复用 (-60%)     │
│ 记忆合并        │  ✅ 已有     │ ✅ 保留并增强          │
└─────────────────┴─────────────┴─────────────────────────┘
```

---

## 2. 技术对比分析

### 2.1 当前 Agent Zero 记忆系统

```
python/helpers/
├── memory.py                 # 核心记忆管理
├── memory_consolidation.py   # 智能记忆合并
└── knowledge_import.py       # 知识导入

关键特点:
- 向量存储: FAISS (IndexFlatIP, 余弦相似度)
- Embedding: LangChain + LiteLLM (多 Provider)
- 知识分区: MAIN, FRAGMENTS, SOLUTIONS, INSTRUMENTS
- 智能合并: MERGE, REPLACE, UPDATE, KEEP_SEPARATE, SKIP
```

### 2.2 OpenClaw 记忆系统优势

```
src/memory/
├── manager.ts                # 记忆管理器 (2200+ 行)
├── embeddings.ts             # Embedding 提供者
├── hybrid.ts                 # 混合检索
├── batch-openai.ts           # 批量 Embedding
└── session-files.ts          # 会话文件管理

关键优势:
- 混合检索: 向量 (sqlite-vec) + 关键词 (FTS5)
- 融合算法: RRF (Reciprocal Rank Fusion)
- 会话索引: 自动索引会话历史
- 文件监控: chokidar 实时监控
- 增量同步: Hash-based 变更检测
- Embedding 缓存: SQLite 持久化缓存
```

### 2.3 技术差距分析

| 技术点 | Agent Zero | OpenClaw | 差距 |
|--------|------------|----------|------|
| 向量检索 | ✅ FAISS | ✅ sqlite-vec | 平手 |
| 关键词检索 | ❌ 无 | ✅ FTS5 | 🔴 缺失 |
| 混合排序 | ❌ 无 | ✅ RRF | 🔴 缺失 |
| 会话持久化 | ❌ 无 | ✅ JSONL + 索引 | 🔴 缺失 |
| 文件监控 | ❌ 无 | ✅ chokidar | 🔴 缺失 |
| 增量同步 | ❌ 全量 | ✅ Hash-based | 🔴 缺失 |
| Embedding 缓存 | ✅ 文件系统 | ✅ SQLite | 🟡 可优化 |
| 记忆合并 | ✅ LLM 智能 | ❌ 无 | 🟢 Agent Zero 优势 |

---

## 3. 整体架构设计

### 3.1 目标架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                     EnhancedMemorySystem                            │
│                        (统一入口)                                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ HybridMemory  │      │SessionManager │      │MemoryWatcher  │
│ (混合检索)    │      │ (会话管理)    │      │ (文件监控)    │
└───────┬───────┘      └───────┬───────┘      └───────┬───────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ FAISS向量库   │      │ JSONL会话文件 │      │  watchdog     │
│ FTS5全文索引  │      │ 会话向量索引  │      │  (OS事件)     │
└───────────────┘      └───────────────┘      └───────────────┘
        │                      │
        └──────────┬───────────┘
                   ▼
           ┌───────────────┐
           │MemoryConsoli- │
           │   dator       │
           │ (智能合并)    │
           └───────────────┘
                   │
                   ▼
           ┌───────────────┐
           │EmbeddingCache │
           │ (SQLite缓存)  │
           └───────────────┘
```

### 3.2 文件结构规划

```
python/helpers/
├── memory.py                    # 现有 (保持兼容, 小修改)
├── memory_consolidation.py      # 现有 (保留)
├── memory_hybrid.py             # 🆕 混合检索
├── memory_fts.py                # 🆕 FTS5 全文搜索
├── memory_session.py            # 🆕 会话持久化
├── memory_watcher.py            # 🆕 文件监控
├── memory_cache.py              # 🆕 Embedding 缓存
├── memory_sync.py               # 🆕 增量同步
└── memory_enhanced.py           # 🆕 统一入口

prompts/default/
├── memory.hybrid_search.sys.md  # 🆕 混合搜索系统提示
└── memory.session_summary.md    # 🆕 会话摘要提示

memory/
├── default/
│   ├── index.faiss              # 现有向量索引
│   ├── fts.db                   # 🆕 FTS5 索引
│   ├── cache.db                 # 🆕 Embedding 缓存
│   └── sessions/                # 🆕 会话文件目录
│       ├── session_001.jsonl
│       └── session_002.jsonl
└── embeddings/                  # 现有 Embedding 缓存目录
```

### 3.3 数据流设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                          写入流程                                    │
└─────────────────────────────────────────────────────────────────────┘

用户/Agent 保存记忆
        │
        ▼
┌───────────────┐
│检查 Embedding │
│    缓存       │──────┐
└───────┬───────┘      │ 命中
        │ 未命中        ▼
        ▼          ┌───────────────┐
┌───────────────┐  │ 直接使用缓存  │
│计算 Embedding │  │   的向量      │
└───────┬───────┘  └───────┬───────┘
        │                  │
        ├──────────────────┘
        ▼
┌───────────────┐
│ 更新缓存      │
└───────┬───────┘
        ▼
┌───────────────┐
│ 记忆合并分析  │ (MemoryConsolidator)
└───────┬───────┘
        │
        ├───────────────────────────────┐
        ▼                               ▼
┌───────────────┐               ┌───────────────┐
│ 写入 FAISS    │               │ 写入 FTS5     │
│   向量库      │               │  全文索引     │
└───────────────┘               └───────────────┘


┌─────────────────────────────────────────────────────────────────────┐
│                          检索流程                                    │
└─────────────────────────────────────────────────────────────────────┘

搜索请求 (query)
        │
        ├─────────────────────────────────┐
        ▼                                 ▼
┌───────────────┐                 ┌───────────────┐
│ 向量检索      │                 │ 关键词检索    │
│ (FAISS)       │                 │ (FTS5 BM25)   │
└───────┬───────┘                 └───────┬───────┘
        │                                 │
        └────────────┬────────────────────┘
                     ▼
             ┌───────────────┐
             │  RRF 融合排序  │
             │ (Reciprocal   │
             │  Rank Fusion) │
             └───────┬───────┘
                     ▼
             ┌───────────────┐
             │  返回结果     │
             └───────────────┘
```

---

## 4. 分阶段实施计划

### 4.1 阶段概览

```
┌──────────────────────────────────────────────────────────────────────┐
│  阶段 1: 基础设施 (2天)                                              │
│  ├─ Embedding 缓存 (SQLite)                                         │
│  └─ 增量同步基础设施                                                 │
├──────────────────────────────────────────────────────────────────────┤
│  阶段 2: 混合检索 (3天)                                              │
│  ├─ FTS5 全文索引                                                    │
│  ├─ RRF 融合算法                                                     │
│  └─ HybridMemory 类                                                  │
├──────────────────────────────────────────────────────────────────────┤
│  阶段 3: 会话管理 (2天)                                              │
│  ├─ 会话持久化 (JSONL)                                               │
│  ├─ 会话索引                                                         │
│  └─ 会话检索 API                                                     │
├──────────────────────────────────────────────────────────────────────┤
│  阶段 4: 实时监控 (1天)                                              │
│  ├─ watchdog 文件监控                                                │
│  └─ 自动增量索引                                                     │
├──────────────────────────────────────────────────────────────────────┤
│  阶段 5: 整合测试 (2天)                                              │
│  ├─ EnhancedMemorySystem 整合                                        │
│  ├─ 单元测试                                                         │
│  └─ 集成测试                                                         │
└──────────────────────────────────────────────────────────────────────┘

总计: 10 个工作日
```

---

### 4.2 阶段 1: 基础设施 (Day 1-2)

#### 4.2.1 Embedding 缓存模块

**目标**: 减少重复 Embedding 计算，降低 API 成本

**文件**: `python/helpers/memory_cache.py`

```python
# 核心类设计
class EmbeddingCache:
    """
    SQLite-based Embedding 缓存
    
    特性:
    - 持久化存储 (SQLite)
    - LRU 清理策略
    - 多 Provider/Model 支持
    - 批量操作优化
    """
    
    def __init__(self, db_path: str, max_entries: int = 100000):
        pass
    
    def get(self, text: str, provider: str, model: str) -> Optional[List[float]]:
        """获取缓存的 embedding"""
        pass
    
    def get_batch(self, texts: List[str], provider: str, model: str) -> Dict[str, List[float]]:
        """批量获取缓存"""
        pass
    
    def set(self, text: str, provider: str, model: str, embedding: List[float]):
        """保存 embedding"""
        pass
    
    def set_batch(self, items: List[Tuple[str, List[float]]], provider: str, model: str):
        """批量保存"""
        pass
    
    def stats(self) -> Dict[str, Any]:
        """缓存统计信息"""
        pass
```

**数据库 Schema**:

```sql
CREATE TABLE embedding_cache (
    hash TEXT PRIMARY KEY,          -- 文本 SHA256 hash
    provider TEXT NOT NULL,         -- 如 'openai', 'gemini'
    model TEXT NOT NULL,            -- 如 'text-embedding-3-small'
    embedding BLOB NOT NULL,        -- float32 数组
    dims INTEGER NOT NULL,          -- 向量维度
    created_at TEXT NOT NULL,
    accessed_at TEXT NOT NULL
);

CREATE INDEX idx_provider_model ON embedding_cache(provider, model);
CREATE INDEX idx_accessed ON embedding_cache(accessed_at);
```

**验收标准**:
- [ ] 缓存命中时, Embedding 计算时间 < 10ms
- [ ] 缓存未命中时, 自动存储新计算的 embedding
- [ ] LRU 清理正常工作, 不超过 max_entries

---

#### 4.2.2 增量同步模块

**目标**: 基于 Hash 的变更检测，避免重复索引

**文件**: `python/helpers/memory_sync.py`

```python
class MemorySyncManager:
    """
    增量同步管理器
    
    特性:
    - 文件 Hash 追踪
    - 脏文件队列
    - 批量同步
    """
    
    def __init__(self, memory: Memory, state_db_path: str):
        pass
    
    def check_file_changed(self, filepath: str) -> bool:
        """检查文件是否变化"""
        pass
    
    def mark_synced(self, filepath: str, hash: str):
        """标记文件已同步"""
        pass
    
    async def sync_changed_files(self, files: List[str]) -> SyncResult:
        """同步变化的文件"""
        pass
```

**交付物**:
- `memory_cache.py` - Embedding 缓存
- `memory_sync.py` - 增量同步
- 单元测试文件

---

### 4.3 阶段 2: 混合检索 (Day 3-5)

#### 4.3.1 FTS5 全文索引模块

**目标**: 实现基于 SQLite FTS5 的关键词检索

**文件**: `python/helpers/memory_fts.py`

```python
class FTSIndex:
    """
    FTS5 全文搜索索引
    
    特性:
    - Porter 词干提取
    - Unicode 支持
    - BM25 排序
    - 高亮摘要
    """
    
    FTS_TABLE = "memory_fts"
    
    def __init__(self, db_path: str):
        pass
    
    def add_document(self, doc_id: str, content: str, metadata: dict):
        """添加文档到索引"""
        pass
    
    def remove_document(self, doc_id: str):
        """从索引删除文档"""
        pass
    
    def search(self, query: str, limit: int = 10, filter: str = "") -> List[FTSResult]:
        """搜索文档"""
        pass
    
    def build_query(self, raw_query: str) -> str:
        """构建 FTS5 查询语法"""
        pass
```

**FTS5 表结构**:

```sql
CREATE VIRTUAL TABLE memory_fts USING fts5(
    id,
    content,
    area,
    source_file,
    timestamp,
    tokenize='porter unicode61 remove_diacritics 2'
);
```

---

#### 4.3.2 RRF 融合算法

**目标**: 实现 Reciprocal Rank Fusion 多路召回融合

**算法公式**:
```
RRF_score(d) = Σ (weight_i / (k + rank_i(d)))

其中:
- d: 文档
- weight_i: 第 i 个检索器的权重
- k: 常数 (通常为 60)
- rank_i(d): 文档 d 在第 i 个检索器中的排名
```

```python
def reciprocal_rank_fusion(
    vector_results: List[SearchResult],
    keyword_results: List[SearchResult],
    vector_weight: float = 0.7,
    text_weight: float = 0.3,
    k: int = 60
) -> List[SearchResult]:
    """
    RRF 融合算法
    
    Args:
        vector_results: 向量检索结果
        keyword_results: 关键词检索结果
        vector_weight: 向量权重 (默认 0.7)
        text_weight: 关键词权重 (默认 0.3)
        k: RRF 常数 (默认 60)
    
    Returns:
        融合排序后的结果列表
    """
    pass
```

---

#### 4.3.3 HybridMemory 类

**目标**: 统一的混合检索接口

**文件**: `python/helpers/memory_hybrid.py`

```python
class HybridMemory(Memory):
    """
    混合检索记忆系统
    
    继承自 Memory, 扩展混合检索能力
    """
    
    def __init__(
        self,
        db: MyFaiss,
        memory_subdir: str,
        fts_db_path: str,
        hybrid_config: HybridConfig = None
    ):
        super().__init__(db, memory_subdir)
        self.fts = FTSIndex(fts_db_path)
        self.config = hybrid_config or HybridConfig()
    
    async def insert_text(self, text: str, metadata: dict = {}) -> str:
        """插入文本到向量库和 FTS 索引"""
        # 1. 调用父类插入向量
        doc_id = await super().insert_text(text, metadata)
        
        # 2. 同步到 FTS 索引
        self.fts.add_document(doc_id, text, metadata)
        
        return doc_id
    
    async def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7,
        filter: str = ""
    ) -> List[Document]:
        """混合检索"""
        pass
    
    async def delete_documents_by_ids(self, ids: List[str]):
        """删除文档 (同时从向量库和 FTS)"""
        await super().delete_documents_by_ids(ids)
        for doc_id in ids:
            self.fts.remove_document(doc_id)


@dataclass
class HybridConfig:
    """混合检索配置"""
    vector_weight: float = 0.7
    text_weight: float = 0.3
    rrf_k: int = 60
    candidate_multiplier: int = 3
    enable_fts: bool = True
```

**交付物**:
- `memory_fts.py` - FTS5 索引
- `memory_hybrid.py` - 混合检索
- 单元测试文件

---

### 4.4 阶段 3: 会话管理 (Day 6-7)

#### 4.4.1 会话持久化

**目标**: 自动保存对话历史，支持检索

**文件**: `python/helpers/memory_session.py`

```python
class SessionMemoryManager:
    """
    会话记忆管理器
    
    特性:
    - JSONL 格式存储
    - 增量索引
    - 语义搜索
    - 会话摘要生成
    """
    
    def __init__(
        self,
        memory: Memory,
        sessions_dir: str,
        chunk_size: int = 10
    ):
        pass
    
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict = {}
    ):
        """保存消息到会话文件"""
        pass
    
    async def sync_sessions(self, force: bool = False):
        """同步会话文件到向量索引"""
        pass
    
    async def search_sessions(
        self,
        query: str,
        limit: int = 5,
        session_id: Optional[str] = None
    ) -> List[SessionSearchResult]:
        """语义搜索会话历史"""
        pass
    
    async def get_session_summary(self, session_id: str) -> str:
        """生成会话摘要"""
        pass
```

**会话文件格式** (JSONL):

```json
{"role": "user", "content": "请帮我分析...", "timestamp": "2026-01-30T21:00:00"}
{"role": "assistant", "content": "好的，我来分析...", "timestamp": "2026-01-30T21:00:05"}
```

**交付物**:
- `memory_session.py` - 会话管理
- `prompts/default/memory.session_summary.md` - 会话摘要提示
- 单元测试文件

---

### 4.5 阶段 4: 实时监控 (Day 8)

#### 4.5.1 文件监控模块

**目标**: 实时监控知识库文件变化，自动触发索引更新

**文件**: `python/helpers/memory_watcher.py`

**依赖**: `watchdog` (需添加到 requirements.txt)

```python
class MemoryFileWatcher:
    """
    文件系统监控器
    
    特性:
    - 实时文件变更检测
    - 防抖处理
    - 增量索引触发
    """
    
    def __init__(
        self,
        memory: Memory,
        watch_dirs: List[str],
        debounce_seconds: float = 2.0,
        file_patterns: List[str] = ["*.md", "*.txt"]
    ):
        pass
    
    def start(self):
        """启动监控"""
        pass
    
    def stop(self):
        """停止监控"""
        pass
    
    async def on_file_changed(self, filepath: str, event_type: str):
        """文件变更回调"""
        pass
```

**监控的目录**:
- `knowledge/default/`
- `knowledge/custom/`
- 用户配置的额外目录

**交付物**:
- `memory_watcher.py` - 文件监控
- requirements.txt 更新 (添加 watchdog)
- 单元测试文件

---

### 4.6 阶段 5: 整合测试 (Day 9-10)

#### 4.6.1 统一入口

**目标**: 提供统一的增强记忆系统入口

**文件**: `python/helpers/memory_enhanced.py`

```python
class EnhancedMemorySystem:
    """
    增强记忆系统 - 统一入口
    
    整合所有增强功能:
    - 混合检索
    - 会话管理
    - 文件监控
    - 记忆合并
    - Embedding 缓存
    """
    
    def __init__(
        self,
        agent: Agent,
        config: EnhancedMemoryConfig = None
    ):
        pass
    
    async def initialize(self):
        """初始化所有子系统"""
        pass
    
    async def save(self, text: str, area: str = "main", **metadata) -> str:
        """保存记忆 (带智能合并)"""
        pass
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        use_hybrid: bool = True,
        include_sessions: bool = False
    ) -> List[Document]:
        """智能搜索"""
        pass
    
    async def save_conversation(self, session_id: str, role: str, content: str):
        """保存对话"""
        pass
    
    def status(self) -> Dict[str, Any]:
        """系统状态"""
        pass
    
    def shutdown(self):
        """关闭系统"""
        pass


@dataclass
class EnhancedMemoryConfig:
    """增强记忆系统配置"""
    enable_hybrid: bool = True
    enable_sessions: bool = True
    enable_watcher: bool = True
    enable_consolidation: bool = True
    enable_cache: bool = True
    
    hybrid: HybridConfig = field(default_factory=HybridConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
```

---

#### 4.6.2 测试计划

**单元测试**:

| 测试文件 | 覆盖模块 | 测试点 |
|----------|----------|--------|
| test_memory_cache.py | memory_cache.py | 缓存读写、LRU 清理、批量操作 |
| test_memory_fts.py | memory_fts.py | FTS 索引、查询语法、BM25 排序 |
| test_memory_hybrid.py | memory_hybrid.py | RRF 融合、混合检索、阈值过滤 |
| test_memory_session.py | memory_session.py | 会话保存、增量同步、语义搜索 |
| test_memory_watcher.py | memory_watcher.py | 文件监控、防抖、回调 |
| test_memory_enhanced.py | memory_enhanced.py | 整合测试、端到端流程 |

**集成测试**:

```python
# tests/integration/test_enhanced_memory_e2e.py

async def test_full_workflow():
    """端到端测试"""
    # 1. 初始化
    system = EnhancedMemorySystem(agent)
    await system.initialize()
    
    # 2. 保存记忆 (触发合并)
    id1 = await system.save("Python 是一种编程语言")
    id2 = await system.save("Python 是解释型语言")  # 应该触发合并
    
    # 3. 混合检索
    results = await system.search("Python 语言", use_hybrid=True)
    assert len(results) > 0
    
    # 4. 保存会话
    await system.save_conversation("sess1", "user", "什么是 Python?")
    await system.save_conversation("sess1", "assistant", "Python 是...")
    
    # 5. 搜索会话
    results = await system.search("Python", include_sessions=True)
    assert any(r.metadata.get("area") == "sessions" for r in results)
    
    # 6. 状态检查
    status = system.status()
    assert status["hybrid"]["enabled"] == True
    assert status["cache"]["hit_rate"] > 0
    
    # 7. 关闭
    system.shutdown()
```

---

## 5. 模块详细设计

### 5.1 模块依赖关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│          memory_enhanced.py (统一入口)                              │
│                    │                                                │
│    ┌───────────────┼───────────────┬─────────────────┐             │
│    │               │               │                 │             │
│    ▼               ▼               ▼                 ▼             │
│ memory_       memory_         memory_           memory_            │
│ hybrid.py     session.py      watcher.py        consolidation.py   │
│    │               │               │                 │             │
│    ▼               │               │                 │             │
│ memory_            │               │                 │             │
│ fts.py             └───────────────┼─────────────────┘             │
│    │                               │                               │
│    └───────────────┬───────────────┘                               │
│                    ▼                                               │
│              memory.py (现有)                                       │
│                    │                                               │
│                    ▼                                               │
│              memory_cache.py                                        │
│              memory_sync.py                                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 配置系统

**配置文件位置**: `conf/memory_enhanced.yaml`

```yaml
# 增强记忆系统配置
memory_enhanced:
  enabled: true
  
  # 混合检索配置
  hybrid:
    enabled: true
    vector_weight: 0.7
    text_weight: 0.3
    rrf_k: 60
    candidate_multiplier: 3
  
  # 会话管理配置
  sessions:
    enabled: true
    chunk_size: 10
    auto_sync: true
    sync_interval_seconds: 60
  
  # 文件监控配置
  watcher:
    enabled: true
    debounce_seconds: 2.0
    watch_dirs:
      - "knowledge/default"
      - "knowledge/custom"
    file_patterns:
      - "*.md"
      - "*.txt"
  
  # Embedding 缓存配置
  cache:
    enabled: true
    max_entries: 100000
    db_path: "memory/{subdir}/cache.db"
  
  # 记忆合并配置
  consolidation:
    enabled: true
    similarity_threshold: 0.7
    replace_similarity_threshold: 0.9
    max_similar_memories: 10
```

---

## 6. 测试与验收标准

### 6.1 功能验收标准

| 功能 | 验收标准 | 测试方法 |
|------|----------|----------|
| Embedding 缓存 | 缓存命中时延迟 < 10ms | 性能测试 |
| FTS5 索引 | 支持中英文搜索 | 功能测试 |
| 混合检索 | 召回率提升 20%+ | A/B 测试 |
| RRF 融合 | 排序结果符合预期 | 人工评估 |
| 会话持久化 | 重启后会话可恢复 | 功能测试 |
| 会话检索 | 能检索历史对话 | 功能测试 |
| 文件监控 | 2 秒内触发索引 | 性能测试 |
| 增量同步 | 未变化文件不重建索引 | 日志检查 |

### 6.2 性能验收标准

| 指标 | 目标 | 测量方法 |
|------|------|----------|
| 缓存命中率 | > 60% | 运行时统计 |
| 混合检索延迟 | < 500ms | 性能测试 |
| 内存占用增量 | < 100MB | 内存监控 |
| 启动时间增量 | < 3s | 计时 |

### 6.3 兼容性验收标准

- [ ] 现有 Memory 类 API 不变
- [ ] 现有 memory_save/memory_load 工具正常工作
- [ ] 现有记忆合并功能正常
- [ ] 不影响现有 Agent 行为

---

## 7. 风险评估与缓解

### 7.1 技术风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| FAISS 与 FTS5 数据不一致 | 中 | 高 | 事务性更新，定期一致性检查 |
| 文件监控资源占用高 | 低 | 中 | 限制监控目录数量，设置防抖 |
| SQLite 并发写入冲突 | 中 | 中 | 使用 WAL 模式，加锁控制 |
| LLM 合并分析超时 | 中 | 低 | 设置超时，fallback 直接插入 |

### 7.2 兼容性风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| 现有 Memory API 变更 | 低 | 高 | 继承而非修改，保持接口兼容 |
| 依赖版本冲突 | 低 | 中 | 明确版本约束 |
| Python 版本兼容 | 低 | 中 | 测试 Python 3.10+ |

---

## 8. 会话策略 (Session Policy)

> **新增功能**: 整合自 OpenClaw `src/sessions/send-policy.ts`

### 8.1 功能描述

会话策略系统控制会话消息的发送行为，支持模型覆盖和级别覆盖。

### 8.2 核心功能

| 功能 | 说明 |
|------|------|
| 发送策略 | 控制消息发送条件和时机 |
| 模型覆盖 | 单会话指定使用不同的 LLM 模型 |
| 级别覆盖 | 单会话调整日志级别 |

### 8.3 数据结构

```python
@dataclass
class SessionPolicy:
    """会话策略配置"""
    session_id: str
    
    # 模型覆盖
    model_override: Optional[str] = None      # 如 "gpt-4o" 覆盖默认模型
    fallback_model: Optional[str] = None      # 备用模型
    
    # 消息发送策略
    send_mode: str = "default"                # default | immediate | batched | silent
    batch_size: int = 1                       # batched 模式下的批量大小
    batch_timeout: float = 5.0                # 批量超时 (秒)
    
    # 日志覆盖
    log_level_override: Optional[str] = None  # DEBUG | INFO | WARNING | ERROR
    
    # 高级选项
    max_context_messages: int = 50            # 上下文最大消息数
    include_system_prompt: bool = True        # 是否包含系统提示
```

### 8.4 实现方式

**文件**: `python/helpers/session_policy.py`

```python
from typing import Dict, Optional
from dataclasses import dataclass, field

@dataclass 
class SessionPolicy:
    session_id: str
    model_override: Optional[str] = None
    fallback_model: Optional[str] = None
    send_mode: str = "default"
    log_level_override: Optional[str] = None
    max_context_messages: int = 50


class SessionPolicyManager:
    """会话策略管理器"""
    
    def __init__(self):
        self._policies: Dict[str, SessionPolicy] = {}
        self._default_policy = SessionPolicy(session_id="__default__")
    
    def get_policy(self, session_id: str) -> SessionPolicy:
        """获取会话策略"""
        return self._policies.get(session_id, self._default_policy)
    
    def set_policy(self, session_id: str, policy: SessionPolicy):
        """设置会话策略"""
        self._policies[session_id] = policy
    
    def get_effective_model(self, session_id: str, default_model: str) -> str:
        """获取有效模型 (考虑覆盖)"""
        policy = self.get_policy(session_id)
        return policy.model_override or default_model
    
    def clear_policy(self, session_id: str):
        """清除会话策略"""
        self._policies.pop(session_id, None)

# 全局实例
_policy_manager = SessionPolicyManager()

def get_session_policy(session_id: str) -> SessionPolicy:
    return _policy_manager.get_policy(session_id)

def set_session_policy(session_id: str, **kwargs):
    policy = SessionPolicy(session_id=session_id, **kwargs)
    _policy_manager.set_policy(session_id, policy)
```

### 8.5 使用示例

```python
# 1. 设置模型覆盖
from python.helpers.session_policy import set_session_policy

set_session_policy(
    "sess-123",
    model_override="gpt-4o",       # 此会话使用 GPT-4o
    fallback_model="gpt-3.5-turbo" # 失败时用 3.5
)

# 2. 调整日志级别
set_session_policy(
    "sess-456",
    log_level_override="DEBUG"     # 此会话开启调试日志
)

# 3. 在 Agent 中使用
policy = get_session_policy(context.session_id)
model = policy.model_override or config.default_model
```

### 8.6 与 Memory 系统集成

在 `memory_session.py` 中集成策略:

```python
class SessionManager:
    def __init__(self):
        self.policy_manager = SessionPolicyManager()
    
    def save_message(self, session_id: str, role: str, content: str):
        policy = self.policy_manager.get_policy(session_id)
        
        # 检查发送模式
        if policy.send_mode == "silent":
            return  # 不保存
        
        # 应用上下文限制
        self._trim_context(session_id, policy.max_context_messages)
        
        # 正常保存
        self._append_message(session_id, role, content)
```

### 8.7 配置

在 `conf/memory_enhanced.yaml` 中添加:

```yaml
memory_enhanced:
  sessions:
    # ... 现有配置 ...
    
    # 会话策略配置
    policy:
      enabled: true
      default_send_mode: "default"
      default_max_context: 50
      allow_model_override: true
```

---

## 9. 后续优化方向

### 9.1 短期优化 (1-2 周)

- [ ] 支持更多 Embedding 模型 (如本地 BGE)
- [ ] 会话摘要自动生成
- [ ] 多语言分词优化 (jieba)

### 9.2 中期优化 (1-2 月)

- [ ] 知识图谱集成 (Neo4j/NetworkX)
- [ ] 多跳检索 (Multi-hop Retrieval)
- [ ] 时间感知检索 (Time-aware)

### 9.3 长期愿景

- [ ] 与 MCP 工具集成
- [ ] 分布式记忆存储
- [ ] 自动知识蒸馏

---

## 附录

### A. 依赖清单

```
# requirements.txt 新增
watchdog>=3.0.0
```

### B. 参考资料

- [OpenClaw Memory Manager](https://github.com/your-org/openclaw/blob/main/src/memory/manager.ts)
- [SQLite FTS5 Documentation](https://www.sqlite.org/fts5.html)
- [RRF Paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [FAISS Documentation](https://faiss.ai/)

### C. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.0 | 2026-01-30 | 初始版本 |

---

> **文档维护者**: AI Assistant  
> **最后更新**: 2026-01-30
