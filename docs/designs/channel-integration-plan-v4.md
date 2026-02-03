# Agent Zero 多渠道网关开发计划 V4

> **版本**: 4.2
> **创建日期**: 2026-02-01
> **更新日期**: 2026-02-01
> **目标**: 为 Agent Zero 构建统一的消息网关，采用**单进程并行架构**，Gateway 专注渠道接入，Web UI 保持原有架构，共享 AgentContext

---

## 🎯 设计说明

本文档借鉴 **OpenClaw** (TypeScript/Node.js) 项目的渠道接入设计理念，为 **Agent Zero** (Python) 实现功能等价的网关系统。

> **⚠️ 重要**: 这是**概念移植**而非代码搬运。两个项目语言不同，所有实现均为 Python 原生代码。

| OpenClaw 设计理念 | Agent Zero 实现方式 |
|------------------|-------------------|
| Gateway 常驻进程 | FastAPI + uvicorn 后台线程 |
| 渠道作为插件 | ChannelAdapter 抽象基类 + 具体适配器 |
| 事件驱动架构 | Extension 扩展点机制 |
| 统一消息协议 | InboundMessage / OutboundMessage 数据类 |
| 会话管理 | AgentContext 共享机制 |

---

## 📚 相关文档

> **⚠️ 重要**: 在实施前请先阅读调研文档和补充文档，其中包含对本文档假设的验证、关键修正和功能增强。

| 文档 | 说明 |
|------|------|
| [agent-zero-api-research.md](./agent-zero-api-research.md) | Agent Zero API 调研文档，包含详细的接口验证和源码分析 |
| [channel-integration-supplement.md](./channel-integration-supplement.md) | 🆕 **补充文档**，包含审阅修正、风险修复和功能增强 |

### 🆕 补充文档核心内容

| 类别 | 内容 | 重要性 |
|------|------|--------|
| 🔴 高风险修正 | AgentBridge 线程安全、Discord 生命周期管理 | **必须修复** |
| 🟡 中风险修正 | 流式响应竞态、附件清理、优雅降级 | 建议修复 |
| 🟢 功能补充 | 消息去重、会话清理、Gateway Extension | 可选增强 |
| 📝 实现补充 | Telegram/Discord 流式编辑完整实现 | 必须补充 |

### 关键修正摘要

基于调研文档的验证，以下是本开发计划需要注意的关键修正：

| 原计划 | 修正后 | 原因 |
|--------|--------|------|
| `await task.wait()` | `await task.result()` | `DeferredTask` 没有 `wait()` 方法 |
| 直接注入 `_gateway_stream_callback` | 通过 Extension 扩展点机制 | Agent Zero 使用 Extension 处理流式响应 |
| `Settings().get_agent_config()` | `initialize_agent()` | Settings 类没有此方法 |
| 附件使用 URL | 附件必须是**本地文件路径** | UserMessage.attachments 只接受本地路径 |

---

## 📋 目录

- [1. 项目概述](#1-项目概述)
- [2. 开发环境](#2-开发环境)
- [3. 整体架构设计](#3-整体架构设计)
- [4. Agent Zero 集成规范](#4-agent-zero-集成规范)
- [5. Gateway 核心框架](#5-gateway-核心框架)
- [6. 渠道适配器](#6-渠道适配器)
- [7. 流式响应策略](#7-流式响应策略)
- [8. 错误恢复与监控](#8-错误恢复与监控)
- [9. 安全模块](#9-安全模块)
- [10. 高级功能](#10-高级功能)
- [11. 部署与运维](#11-部署与运维)
- [12. 测试与验收](#12-测试与验收)

---

## 1. 项目概述

### 1.1 背景

借鉴 OpenClaw 的核心设计理念，为 Agent Zero 构建一个**常驻运行的 Gateway 进程**，所有外部渠道（Telegram、Discord 等）都作为 Gateway 的插件运行。

### 1.2 V4.1 改进要点

| 改进项 | V3/V4.0 状态 | V4.1 解决方案 |
|--------|---------|-------------|
| Web UI 集成 | ❌ 未明确 | ✅ 单进程并行架构 |
| Agent 集成 | ❌ 占位符 | ✅ AgentBridge 桥接层 + 流式回调 |
| 流式响应 | ⚠️ 集成点不明 | ✅ Hook Agent 回调机制 |
| 错误恢复 | ❌ 缺失 | ✅ 指数退避重连 |
| 安全模块 | ❌ 未实现 | ✅ SecurityManager |
| Discord 线程安全 | ⚠️ 隐患 | ✅ `run_coroutine_threadsafe` 方案 |
| 热重载行为 | ⚠️ 不明确 | ✅ 行为矩阵 |
| 监控指标 | ❌ 缺失 | ✅ MetricsCollector |
| AgentContext 共享 | ⚠️ 跨进程问题 | ✅ 单进程架构解决 |

### 1.3 核心架构：单进程并行模式

> **关键决策**: Gateway 和 Web UI 运行在**同一 Python 进程**中，通过线程隔离实现并行，共享内存中的 `AgentContext._contexts` 字典。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      单进程并行架构 (推荐方案)                                │
│                      Python Process (PID: xxx)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────────────┐   ┌─────────────────────────────────────┐ │
│   │      Web UI 线程             │   │      Gateway 线程                   │ │
│   │      (Flask + 60+ API)       │   │      (FastAPI + uvicorn)            │ │
│   │      端口: 50001             │   │      端口: 18900                    │ │
│   │                              │   │                                      │ │
│   │   ┌──────────────┐          │   │   ┌──────────────┐                   │ │
│   │   │ 浏览器前端    │          │   │   │  Telegram    │ (子线程)          │ │
│   │   └──────┬───────┘          │   │   ├──────────────┤                   │ │
│   │          │                   │   │   │  Discord     │ (子线程)          │ │
│   │          ▼                   │   │   └──────┬───────┘                   │ │
│   │   ┌──────────────┐          │   │          │                           │ │
│   │   │ Flask API     │          │   │          ▼                           │ │
│   │   └──────┬───────┘          │   │   ┌──────────────┐                   │ │
│   │          │                   │   │   │ AgentBridge  │                   │ │
│   │          │                   │   │   └──────┬───────┘                   │ │
│   └──────────┼───────────────────┘   └──────────┼───────────────────────────┘ │
│              │                                   │                            │
│              └───────────────┬───────────────────┘                            │
│                              │                                                │
│                              ▼                                                │
│              ┌──────────────────────────────────────┐                        │
│              │      AgentContext._contexts (共享)    │                        │
│              │      dict[str, AgentContext]          │                        │
│              │      (内存字典，无需跨进程通信)         │                        │
│              └──────────────────────────────────────┘                        │
│                              │                                                │
│                              ▼                                                │
│              ┌──────────────────────────────────────┐                        │
│              │        Agent Zero Core               │                        │
│              │   (Agent, History, Memory, LLM)      │                        │
│              └──────────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**单进程架构优势**：
- ✅ **天然共享 AgentContext**：无需 Redis 等外部存储
- ✅ 不修改现有 60+ API Handler
- ✅ Gateway 专注渠道，符合单一职责
- ✅ 资源占用少，部署简单
- ✅ 线程间通信高效，无序列化开销

### 1.4 Phase 1 目标渠道

| 渠道 | Python 库 | 优先级 | 状态 |
|------|-----------|--------|------|
| **Discord** | discord.py | ⭐⭐⭐⭐⭐ | 🔵 Phase 1 |
| **Telegram** | python-telegram-bot | ⭐⭐⭐⭐⭐ | 🔵 Phase 1 |
| Email | smtplib/imaplib | ⭐⭐⭐ | 🟡 后续 |
| Slack | slack-sdk | ⭐⭐⭐ | 🟡 后续 |
| WeChat | wechatpy | ⭐⭐ | 🟡 后续 |
| WhatsApp | Twilio | ⭐⭐ | 🟡 后续 |
| Matrix | matrix-nio | ⭐⭐ | 🟡 后续 |

### 1.5 设计原则

| 原则 | 说明 |
|------|------|
| **并行共存** | Gateway 与 Web UI 独立运行，共享 AgentContext |
| **网关优先** | Gateway 是渠道核心，渠道都是客户端 |
| **统一认证** | 所有请求在 Gateway 层统一验证 Token |
| **统一会话** | 跨渠道会话使用统一格式管理 |
| **常驻运行** | 7x24 运行，支持系统服务托管 |
| **可观测性** | 健康检查、状态 API、监控指标、日志 |
| **可维护性** | 配置热重载、优雅重启 |
| **可扩展性** | 插件化渠道、统一接口 |

---

## 2. 开发环境

### 2.1 环境要求

| 组件 | 要求 |
|------|------|
| **主机系统** | Windows / Mac / Linux |
| **Docker** | Docker Desktop 或 Docker Engine |
| **IDE** | VSCode、Cursor 等（任意） |

### 2.2 开发模式

采用 **Windows 编辑 + Docker 运行** 的模式，统一使用 Linux 命令格式：

```
┌─────────────────────────────────────────────────────────┐
│                    Windows 主机                          │
│  ┌───────────────┐                                      │
│  │  IDE/编辑器    │  ← 只负责写代码                       │
│  └───────┬───────┘                                      │
│          │ 代码挂载 (volume)                             │
│          ▼                                              │
│  ┌───────────────────────────────────────────────────┐  │
│  │              Docker Container                      │  │
│  │  • 运行 Agent Zero + Gateway                       │  │
│  │  • 运行测试                                        │  │
│  │  • 统一使用 Linux 命令                             │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**优势**：
- ✅ 命令统一，文档不用写两套
- ✅ 开发和生产环境完全一致
- ✅ 不污染本地 Python 环境
- ✅ 减少"在我机器上能跑"的问题

### 2.3 快速开始

```bash
# 1. 启动开发环境
docker-compose up -d

# 2. 查看日志
docker-compose logs -f

# 3. 进入容器执行命令
docker-compose exec agent-zero bash

# 4. 在容器内运行测试
pytest tests/ -v

# 5. 在容器内检查 Gateway 状态
curl http://localhost:18900/api/health

# 6. 停止
docker-compose down
```

### 2.4 docker-compose.yml（开发模式）

```yaml
version: "3.8"

services:
  agent-zero:
    build: .
    container_name: agent-zero-dev
    ports:
      - "50001:50001"   # Web UI
      - "18900:18900"   # Gateway
    volumes:
      # 挂载代码目录，修改后立即生效
      - .:/a0
    env_file:
      - .env
    environment:
      - PYTHONDONTWRITEBYTECODE=1
      - DOCKER_CONTAINER=1
    working_dir: /a0
    command: python run_all.py --ui-host 0.0.0.0 --gateway-host 0.0.0.0
    restart: unless-stopped

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18900/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

---

## 3. 整体架构设计

### 3.1 文件结构

```
python/
├── gateway/                        # 🆕 网关核心
│   ├── __init__.py
│   ├── server.py                   # Gateway 服务器 (FastAPI)
│   ├── config.py                   # 配置管理 + 热重载
│   ├── health.py                   # 健康检查
│   ├── protocol.py                 # 通信协议定义
│   ├── agent_bridge.py             # 🆕 Agent 桥接层
│   └── metrics.py                  # 🆕 监控指标
│
├── channels/                       # 渠道模块 (网关插件)
│   ├── __init__.py
│   ├── base.py                     # 适配器基类 + 消息模型
│   ├── manager.py                  # 渠道管理器
│   ├── security.py                 # 🆕 安全模块
│   ├── capability_adapter.py       # 🆕 能力适配器
│   ├── streaming.py                # 🆕 流式响应策略
│   ├── telegram_adapter.py         # Telegram 适配器
│   └── discord_adapter.py          # Discord 适配器 (改进)
│
└── agent.py                        # Agent Zero 核心 (不修改)

conf/
├── gateway.yaml                    # 网关配置
└── channels.yaml                   # 渠道配置 (可选拆分)

run_gateway.py                      # 网关启动入口
```

### 3.2 分阶段实施计划

```
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: Gateway 核心 + AgentBridge (Day 1-4)            【最优先】 │
│  ├─ Gateway Server (FastAPI 基础框架)                                │
│  ├─ AgentBridge 桥接层 (对接 AgentContext/Agent)                    │
│  ├─ 流式响应策略 (Buffer/Edit/Typing)                               │
│  ├─ 配置管理 + 热重载                                               │
│  ├─ 健康检查 + 状态 API                                             │
│  ├─ ChannelManager 框架                                             │
│  ├─ SecurityManager                                                  │
│  └─ MetricsCollector                                                 │
├──────────────────────────────────────────────────────────────────────┤
│  Phase 2: Telegram 适配器 (Day 5-6)                                 │
│  ├─ Bot 连接 + 消息监听                                             │
│  ├─ 流式响应渠道策略                                                 │
│  ├─ 错误恢复 + 重连机制                                             │
│  └─ 集成测试                                                         │
├──────────────────────────────────────────────────────────────────────┤
│  Phase 3: Discord 适配器 (Day 7-9)                                  │
│  ├─ 线程安全消息队列                                                 │
│  ├─ 流式响应渠道策略                                                 │
│  ├─ 错误恢复 + 重连机制                                             │
│  └─ 集成测试                                                         │
├──────────────────────────────────────────────────────────────────────┤
│  Phase 4: 高级功能 + 服务化 (Day 10-11)                             │
│  ├─ 远程访问 (Token 认证)                                            │
│  ├─ 完整监控指标                                                     │
│  ├─ systemd/launchd 服务配置                                        │
│  └─ 完整测试 + 文档                                                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Agent Zero 集成规范

> **核心目标**: 定义 Gateway 如何与 Agent Zero 现有架构对接

### 3.1 AgentBridge 桥接层

**文件**: `python/gateway/agent_bridge.py`

```python
"""
Agent Zero 桥接层

负责:
- 管理 AgentContext 生命周期
- 将渠道消息转换为 Agent 可处理的格式
- 处理流式响应并传递给渠道
"""

import asyncio
import logging
from typing import AsyncGenerator, Dict, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass

# 导入 Agent Zero 核心类
from agent import Agent, AgentContext, AgentConfig, UserMessage, AgentContextType

logger = logging.getLogger("gateway.agent_bridge")


@dataclass
class ChannelSession:
    """渠道会话信息"""
    context_id: str
    channel: str
    channel_user_id: str
    channel_chat_id: str
    user_name: Optional[str] = None
    created_at: datetime = None
    last_activity: datetime = None
    
    def __post_init__(self):
        now = datetime.now(timezone.utc)
        self.created_at = self.created_at or now
        self.last_activity = self.last_activity or now


class AgentBridge:
    """Gateway 与 Agent Zero 的桥接层"""

    def __init__(self, default_config: AgentConfig):
        """
        初始化桥接层
        
        Args:
            default_config: 默认 Agent 配置，从 Agent Zero 现有配置加载
        """
        self.default_config = default_config
        self._sessions: Dict[str, ChannelSession] = {}
        self._response_callbacks: Dict[str, callable] = {}
        
    def _make_session_key(self, channel: str, channel_user_id: str) -> str:
        """生成会话键: {channel}:{user_id}"""
        return f"{channel}:{channel_user_id}"
    
    def get_or_create_context(
        self, 
        channel: str, 
        channel_user_id: str,
        channel_chat_id: str,
        user_name: Optional[str] = None,
        channel_config: Optional[dict] = None,
    ) -> AgentContext:
        """
        获取或创建 AgentContext
        
        会话键格式: {channel}:{user_id}
        例如: telegram:456789, discord:123456789
        """
        session_key = self._make_session_key(channel, channel_user_id)
        
        # 尝试获取现有 context
        existing_ctx = AgentContext.get(session_key)
        if existing_ctx:
            # 更新活动时间
            if session_key in self._sessions:
                self._sessions[session_key].last_activity = datetime.now(timezone.utc)
            return existing_ctx
        
        # 创建新的 context
        # 可选: 从渠道配置覆盖模型设置
        config = self._build_config(channel_config)
        
        ctx = AgentContext(
            config=config,
            id=session_key,
            name=f"{channel}:{user_name or channel_user_id}",
            type=AgentContextType.USER,
        )
        
        # 记录会话信息
        self._sessions[session_key] = ChannelSession(
            context_id=session_key,
            channel=channel,
            channel_user_id=channel_user_id,
            channel_chat_id=channel_chat_id,
            user_name=user_name,
        )
        
        logger.info(f"Created new context: {session_key}")
        return ctx
    
    def _build_config(self, channel_config: Optional[dict] = None) -> AgentConfig:
        """构建 Agent 配置，支持渠道专用配置覆盖"""
        if not channel_config:
            return self.default_config
            
        # 渠道可覆盖的配置项
        model_override = channel_config.get("model_override", {})
        if not model_override:
            return self.default_config
            
        # 创建配置副本并覆盖
        import copy
        config = copy.deepcopy(self.default_config)
        
        # 支持渠道专用模型配置
        # if "chat_model" in model_override:
        #     config.chat_model = ...
            
        return config
    
    async def process_message(
        self,
        channel: str,
        channel_user_id: str,
        channel_chat_id: str,
        content: str,
        user_name: Optional[str] = None,
        attachments: list = None,
        metadata: dict = None,
        channel_config: dict = None,
        stream_callback: callable = None,
    ) -> str:
        """
        处理渠道消息
        
        Args:
            channel: 渠道名称 (telegram, discord)
            channel_user_id: 渠道用户 ID
            channel_chat_id: 渠道会话 ID
            content: 消息内容
            user_name: 用户名
            attachments: 附件列表
            metadata: 额外元数据
            channel_config: 渠道配置
            stream_callback: 流式响应回调 async def(chunk: str, full: str)
            
        Returns:
            Agent 的完整响应
        """
        # 获取或创建 context
        ctx = self.get_or_create_context(
            channel=channel,
            channel_user_id=channel_user_id,
            channel_chat_id=channel_chat_id,
            user_name=user_name,
            channel_config=channel_config,
        )
        
        # 构建 UserMessage
        user_msg = UserMessage(
            message=content,
            attachments=attachments or [],
            system_message=[],  # 可扩展: 从渠道添加系统消息
        )
        
        # 存储渠道元数据到 context
        ctx.set_data("channel_metadata", {
            "channel": channel,
            "chat_id": channel_chat_id,
            "user_id": channel_user_id,
            "user_name": user_name,
            **(metadata or {}),
        })
        
        # 注册流式回调 (如果提供)
        session_key = self._make_session_key(channel, channel_user_id)
        if stream_callback:
            self._response_callbacks[session_key] = stream_callback
        
        try:
            # 调用 Agent 的 communicate 方法
            task = ctx.communicate(user_msg)
            
            # 等待任务完成
            if task:
                response = await task.result()  # ✅ 修正: 使用 result() 而非 wait()
                return response or ""
            return ""

        finally:
            # 清理流式回调
            ctx.set_data("gateway_stream_callback", None)  # ✅ 修正: 通过 context.data 清理
    
    async def process_message_stream(
        self,
        channel: str,
        channel_user_id: str,
        channel_chat_id: str,
        content: str,
        user_name: Optional[str] = None,
        attachments: list = None,
        metadata: dict = None,
        channel_config: dict = None,
    ) -> AsyncGenerator[str, None]:
        """
        处理消息并以流式方式返回响应
        
        Yields:
            响应片段
        """
        response_queue: asyncio.Queue = asyncio.Queue()
        response_complete = asyncio.Event()
        
        async def stream_callback(chunk: str, full: str):
            await response_queue.put(chunk)
        
        # 启动处理任务
        async def process_task():
            try:
                await self.process_message(
                    channel=channel,
                    channel_user_id=channel_user_id,
                    channel_chat_id=channel_chat_id,
                    content=content,
                    user_name=user_name,
                    attachments=attachments,
                    metadata=metadata,
                    channel_config=channel_config,
                    stream_callback=stream_callback,
                )
            finally:
                response_complete.set()
        
        task = asyncio.create_task(process_task())
        
        try:
            while not response_complete.is_set() or not response_queue.empty():
                try:
                    chunk = await asyncio.wait_for(
                        response_queue.get(), 
                        timeout=0.1
                    )
                    yield chunk
                except asyncio.TimeoutError:
                    continue
        finally:
            task.cancel()
    
    def get_session(self, channel: str, channel_user_id: str) -> Optional[ChannelSession]:
        """获取会话信息"""
        session_key = self._make_session_key(channel, channel_user_id)
        return self._sessions.get(session_key)
    
    def list_sessions(self) -> Dict[str, ChannelSession]:
        """列出所有会话"""
        return self._sessions.copy()
    
    def remove_session(self, channel: str, channel_user_id: str) -> bool:
        """移除会话"""
        session_key = self._make_session_key(channel, channel_user_id)
        if session_key in self._sessions:
            del self._sessions[session_key]
            AgentContext.remove(session_key)
            logger.info(f"Removed session: {session_key}")
            return True
        return False
```

### 3.2 流式响应集成 (V4.1 新增)

> **关键发现**: Agent Zero 的 `communicate()` 方法不直接支持流式回调，流式输出在 `Agent.monologue()` 内部通过 LLM 回调实现。

**解决方案**: 通过 Hook Agent 的回调机制实现流式响应传递。

#### Extension 文件命名规范

创建 Extension 文件: `python/extensions/response_stream_chunk/_20_gateway_callback.py`

> **命名规范说明**：
> - 文件名格式：`_{优先级}_{功能名}.py`
> - 优先级数字越小，执行越早
> - `_10_mask_stream.py` - 优先级 10，先执行敏感信息过滤
> - `_20_gateway_callback.py` - 优先级 20，后执行 Gateway 回调
>
> 这样设计确保敏感信息先被过滤，再传递给渠道。

```python
# python/gateway/agent_bridge.py (流式响应增强部分)

class AgentBridge:
    """Gateway 与 Agent Zero 的桥接层 (流式增强版)"""

    def __init__(self, default_config: AgentConfig):
        self.default_config = default_config
        self._sessions = {}
        self._stream_callbacks = {}  # session_key -> callback

    async def process_message_with_stream(
        self,
        channel: str,
        channel_user_id: str,
        channel_chat_id: str,
        content: str,
        stream_callback: Callable[[str, str], Awaitable[None]] = None,
        **kwargs
    ) -> str:
        """
        处理消息并支持流式回调

        Args:
            stream_callback: async def(chunk: str, full: str) 流式回调

        Returns:
            Agent 的完整响应
        """
        session_key = f"{channel}:{channel_user_id}"
        ctx = self.get_or_create_context(channel, channel_user_id, channel_chat_id, **kwargs)

        # ✅ 关键：注入流式回调到 Agent
        if stream_callback:
            self._inject_stream_callback(ctx, session_key, stream_callback)

        user_msg = UserMessage(message=content, attachments=[], system_message=[])

        try:
            task = ctx.communicate(user_msg)
            if task:
                response = await task.result()  # ✅ 修正: 使用 result() 而非 wait()
                return response or ""
            return ""
        finally:
            ctx.set_data("gateway_stream_callback", None)  # ✅ 修正: 通过 context.data 清理

    def _register_stream_callback(self, ctx: AgentContext, callback):
        """
        注册流式回调到 AgentContext

        ✅ 修正: 通过 context.set_data() 注册回调，配合 Extension 扩展点使用

        需要创建 Extension 文件: python/extensions/response_stream_chunk/_20_gateway_callback.py
        Extension 会从 ctx.get_data("gateway_stream_callback") 获取回调并调用
        """
        if callback:
            ctx.set_data("gateway_stream_callback", callback)

    async def process_message_stream(
        self,
        channel: str,
        channel_user_id: str,
        channel_chat_id: str,
        content: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        处理消息并以 AsyncGenerator 方式返回流式响应

        Usage:
            async for chunk in bridge.process_message_stream(...):
                await send_chunk_to_channel(chunk)
        """
        response_queue = asyncio.Queue()
        response_complete = asyncio.Event()

        async def stream_callback(chunk: str, full: str):
            await response_queue.put(chunk)

        async def process_task():
            try:
                await self.process_message_with_stream(
                    channel=channel,
                    channel_user_id=channel_user_id,
                    channel_chat_id=channel_chat_id,
                    content=content,
                    stream_callback=stream_callback,
                    **kwargs
                )
            finally:
                response_complete.set()

        task = asyncio.create_task(process_task())

        try:
            while not response_complete.is_set() or not response_queue.empty():
                try:
                    chunk = await asyncio.wait_for(response_queue.get(), timeout=0.1)
                    yield chunk
                except asyncio.TimeoutError:
                    continue
        finally:
            if not task.done():
                task.cancel()
```

**流式响应使用示例**:

```python
# 在渠道适配器中使用流式响应
async def handle_message_with_streaming(self, inbound: InboundMessage):
    # 发送初始消息（用于后续编辑）
    sent_msg = await self.send_typing_indicator(inbound.channel_chat_id)

    full_response = ""
    last_update = 0

    async for chunk in self.agent_bridge.process_message_stream(
        channel=inbound.channel,
        channel_user_id=inbound.channel_user_id,
        channel_chat_id=inbound.channel_chat_id,
        content=inbound.content,
    ):
        full_response += chunk

        # 每隔 1 秒更新一次消息（避免速率限制）
        now = time.time()
        if now - last_update > 1.0:
            await self.edit_message(sent_msg.id, full_response + "▌")
            last_update = now

    # 最终更新
    await self.edit_message(sent_msg.id, full_response)
```

### 3.3 与现有 Web UI 的会话共享

```python
# 在 Web UI 中使用相同的会话键格式
# python/api/chat.py (现有 Web UI API)

async def handle_chat(request):
    # Web UI 会话键格式: web:{session_id}
    session_key = f"web:{request.session_id}"
    
    # 复用 AgentContext 机制
    ctx = AgentContext.get(session_key)
    if not ctx:
        ctx = AgentContext(config=config, id=session_key)
    
    # ... 处理消息
```

### 3.3 会话键格式规范

| 渠道 | 会话键格式 | 示例 |
|------|-----------|------|
| Web UI | `web:{session_id}` | `web:abc123` |
| Telegram | `telegram:{user_id}` | `telegram:456789` |
| Discord | `discord:{user_id}` | `discord:123456789` |
| Email | `email:{email_addr}` | `email:user@example.com` |

---

## 5. Gateway 核心框架

### 4.1 Gateway Server

**文件**: `python/gateway/server.py`

```python
"""
Agent Zero Gateway Server

核心网关服务器，采用并行共存架构:
- Gateway 专注渠道接入
- Web UI 保持现有 Flask 架构
- 通过共享 AgentContext 实现会话统一
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from .config import GatewayConfig, ConfigWatcher
from .health import HealthChecker, HealthStatus
from .protocol import GatewayEvent, EventType
from .agent_bridge import AgentBridge
from .metrics import MetricsCollector
from ..channels.manager import ChannelManager
from ..channels.security import SecurityManager

logger = logging.getLogger("gateway.server")


@dataclass
class GatewayState:
    """网关运行状态"""
    started_at: datetime = field(default_factory=datetime.now)
    config: GatewayConfig = None
    channel_manager: ChannelManager = None
    agent_bridge: AgentBridge = None
    security_manager: SecurityManager = None
    metrics: MetricsCollector = None
    health_checker: HealthChecker = None
    config_watcher: ConfigWatcher = None
    is_shutting_down: bool = False


# 全局状态
state = GatewayState()
security = HTTPBearer(auto_error=False)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
    """验证 API Token"""
    if not state.config or not state.config.auth_token:
        return True
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    if credentials.credentials != state.config.auth_token:
        raise HTTPException(status_code=403, detail="Invalid token")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Gateway starting...")
    await startup()
    yield
    await shutdown()


async def startup():
    """启动初始化"""
    from ..channels.telegram_adapter import TelegramAdapter
    from ..channels.discord_adapter import DiscordAdapter
    
    # 加载配置
    state.config = GatewayConfig.load()
    logger.info(f"Loaded config from {state.config.config_path}")
    
    # 初始化监控指标
    state.metrics = MetricsCollector()
    
    # 初始化安全管理器
    state.security_manager = SecurityManager(state.config)
    
    # 初始化 AgentBridge
    # ✅ 修正: 使用 initialize_agent() 获取配置
    from initialize import initialize_agent
    agent_config = initialize_agent()
    state.agent_bridge = AgentBridge(agent_config)
    
    # 初始化渠道管理器
    state.channel_manager = ChannelManager(
        agent_bridge=state.agent_bridge,
        security_manager=state.security_manager,
        metrics=state.metrics,
    )
    
    # 注册渠道
    channels_config = state.config.channels
    for channel_name, channel_cfg in channels_config.items():
        if not channel_cfg.get("enabled", False):
            continue
        try:
            if channel_name == "telegram" and channel_cfg.get("token"):
                adapter = TelegramAdapter(channel_cfg, channel_cfg.get("account_id", "default"))
                state.channel_manager.register(f"telegram:{adapter.account_id}", adapter)
            elif channel_name == "discord" and channel_cfg.get("token"):
                adapter = DiscordAdapter(channel_cfg, channel_cfg.get("account_id", "default"))
                state.channel_manager.register(f"discord:{adapter.account_id}", adapter)
        except Exception as e:
            logger.error(f"Failed to register {channel_name}: {e}")
    
    # 启动渠道
    if state.channel_manager.channels:
        await state.channel_manager.start_all()
    
    # 初始化健康检查器
    state.health_checker = HealthChecker(state)
    
    # 启动配置热重载
    if state.config.hot_reload:
        state.config_watcher = ConfigWatcher(state.config.config_path, on_config_change)
        await state.config_watcher.start()
    
    logger.info(f"Gateway started on port {state.config.port}")


async def shutdown():
    """优雅关闭"""
    logger.info("Gateway shutting down...")
    state.is_shutting_down = True
    
    if state.config_watcher:
        await state.config_watcher.stop()
    if state.channel_manager:
        await state.channel_manager.stop_all()
    
    logger.info("Gateway stopped")


async def on_config_change(new_config: dict):
    """配置变更回调"""
    logger.info("Config changed, applying hot reload...")
    # 应用热重载逻辑
    await state.channel_manager.apply_config_change(new_config)


# FastAPI 应用
app = FastAPI(
    title="Agent Zero Gateway",
    version="4.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# HTTP API 端点
@app.get("/api/health")
async def health_check():
    """健康检查"""
    status = await state.health_checker.check()
    return status.__dict__


@app.get("/api/status")
async def gateway_status(authorized: bool = Depends(verify_token)):
    """网关状态"""
    return {
        "started_at": state.started_at.isoformat(),
        "uptime_seconds": (datetime.now() - state.started_at).total_seconds(),
        "channels": state.channel_manager.list_channels() if state.channel_manager else {},
        "sessions": len(state.agent_bridge.list_sessions()) if state.agent_bridge else 0,
        "metrics": state.metrics.get_summary() if state.metrics else {},
    }


@app.get("/api/channels")
async def list_channels(authorized: bool = Depends(verify_token)):
    """列出所有渠道"""
    if not state.channel_manager:
        return {"channels": {}}
    return {"channels": state.channel_manager.list_channels()}


@app.get("/api/metrics")
async def get_metrics(authorized: bool = Depends(verify_token)):
    """获取监控指标"""
    if not state.metrics:
        return {"metrics": {}}
    return {"metrics": state.metrics.get_summary()}


@app.post("/api/reload")
async def reload_config(authorized: bool = Depends(verify_token)):
    """手动触发配置重载"""
    try:
        new_config = GatewayConfig.load()
        await on_config_change(new_config.__dict__)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def run_gateway(host: str = "127.0.0.1", port: int = 18900, reload: bool = False, log_level: str = "info"):
    """运行 Gateway 服务器"""
    uvicorn.run(
        "python.gateway.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )
```

### 4.2 配置管理 + 热重载

**文件**: `python/gateway/config.py`

```python
"""
Gateway 配置管理

支持:
- YAML 配置文件
- 环境变量覆盖
- 配置热重载
"""

import os
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import yaml

logger = logging.getLogger("gateway.config")


@dataclass
class GatewayConfig:
    """网关配置"""
    # 基础配置
    port: int = 18900
    host: str = "127.0.0.1"
    config_path: str = "conf/gateway.yaml"

    # 安全配置
    auth_token: Optional[str] = None
    auth_password: Optional[str] = None

    # 功能开关
    hot_reload: bool = True
    verbose: bool = False

    # 渠道配置
    channels: Dict[str, Any] = field(default_factory=dict)

    # 高级配置
    max_payload_size: int = 10 * 1024 * 1024  # 10MB
    tick_interval_ms: int = 30000  # 30秒心跳
    websocket_timeout: int = 60  # WebSocket 超时

    @classmethod
    def load(cls, config_path: str = None) -> "GatewayConfig":
        """加载配置"""
        path = config_path or os.environ.get("GATEWAY_CONFIG_PATH", "conf/gateway.yaml")

        config = cls(config_path=path)

        # 从文件加载
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            # 网关配置
            gateway = data.get("gateway", {})
            config.port = gateway.get("port", config.port)
            config.host = gateway.get("host", config.host)
            config.hot_reload = gateway.get("hot_reload", config.hot_reload)
            config.verbose = gateway.get("verbose", config.verbose)

            # 认证配置
            auth = gateway.get("auth", {})
            config.auth_token = auth.get("token")
            config.auth_password = auth.get("password")

            # 渠道配置
            config.channels = data.get("channels", {})

        # 环境变量覆盖
        config.port = int(os.environ.get("GATEWAY_PORT", config.port))
        config.host = os.environ.get("GATEWAY_HOST", config.host)
        config.auth_token = os.environ.get("GATEWAY_AUTH_TOKEN", config.auth_token)

        # 替换渠道配置中的环境变量
        config.channels = cls._replace_env_vars(config.channels)

        return config

    @staticmethod
    def _replace_env_vars(obj):
        """递归替换环境变量"""
        if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            env_key = obj[2:-1]
            return os.environ.get(env_key, "")
        elif isinstance(obj, dict):
            return {k: GatewayConfig._replace_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [GatewayConfig._replace_env_vars(item) for item in obj]
        return obj


class ConfigWatcher:
    """配置文件监视器"""

    def __init__(self, config_path: str, callback: Callable):
        self.config_path = Path(config_path)
        self.callback = callback
        self.observer = None
        self._debounce_task = None
        self._debounce_delay = 1.0  # 防抖延迟

    async def start(self):
        """启动监视"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return

        handler = ConfigFileHandler(self._on_change)
        self.observer = Observer()
        self.observer.schedule(handler, str(self.config_path.parent), recursive=False)
        self.observer.start()
        logger.info(f"Watching config file: {self.config_path}")

    async def stop(self):
        """停止监视"""
        if self.observer:
            self.observer.stop()
            self.observer.join()

    def _on_change(self):
        """配置变更处理（带防抖）"""
        if self._debounce_task:
            self._debounce_task.cancel()

        async def debounced_callback():
            await asyncio.sleep(self._debounce_delay)
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    new_config = yaml.safe_load(f)
                await self.callback(new_config)
            except Exception as e:
                logger.error(f"Failed to reload config: {e}")

        self._debounce_task = asyncio.create_task(debounced_callback())


class ConfigFileHandler(FileSystemEventHandler):
    """文件系统事件处理器"""

    def __init__(self, callback: Callable):
        self.callback = callback

    def on_modified(self, event):
        if not event.is_directory:
            self.callback()
```

### 4.3 健康检查

**文件**: `python/gateway/health.py`

```python
"""
Gateway 健康检查

提供:
- 存活探针 (liveness)
- 就绪探针 (readiness)
- 详细状态报告
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from enum import Enum

logger = logging.getLogger("gateway.health")


class HealthStatusLevel(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    """单项健康检查结果"""
    name: str
    status: HealthStatusLevel
    message: Optional[str] = None
    latency_ms: Optional[float] = None


@dataclass
class HealthStatus:
    """整体健康状态"""
    status: str  # healthy, degraded, unhealthy
    uptime_seconds: float
    timestamp: datetime
    channels: Dict[str, Any]
    checks: List[Dict[str, Any]]


class HealthChecker:
    """健康检查器"""

    def __init__(self, gateway_state):
        self.state = gateway_state

    async def check(self) -> HealthStatus:
        """执行健康检查"""
        checks = []
        overall_status = HealthStatusLevel.HEALTHY

        # 检查 1: 网关核心
        gateway_check = await self._check_gateway()
        checks.append(gateway_check)
        if gateway_check.status != HealthStatusLevel.HEALTHY:
            overall_status = gateway_check.status

        # 检查 2: 渠道状态
        channel_checks = await self._check_channels()
        checks.extend(channel_checks)
        for check in channel_checks:
            if check.status == HealthStatusLevel.UNHEALTHY:
                overall_status = HealthStatusLevel.UNHEALTHY
            elif check.status == HealthStatusLevel.DEGRADED and overall_status == HealthStatusLevel.HEALTHY:
                overall_status = HealthStatusLevel.DEGRADED

        # 检查 3: Agent 连接
        agent_check = await self._check_agent()
        checks.append(agent_check)
        if agent_check.status == HealthStatusLevel.UNHEALTHY:
            overall_status = HealthStatusLevel.UNHEALTHY

        # 构建渠道状态摘要
        channels_summary = {}
        if self.state.channel_manager:
            for name, adapter in self.state.channel_manager.channels.items():
                channels_summary[name] = {
                    "type": adapter.__class__.__name__,
                    "running": adapter._running,
                    "capabilities": adapter.capabilities.__dict__,
                }

        return HealthStatus(
            status=overall_status.value,
            uptime_seconds=(datetime.now() - self.state.started_at).total_seconds(),
            timestamp=datetime.now(),
            channels=channels_summary,
            checks=[{
                "name": c.name,
                "status": c.status.value,
                "message": c.message,
                "latency_ms": c.latency_ms,
            } for c in checks],
        )

    async def _check_gateway(self) -> HealthCheck:
        """检查网关核心"""
        if self.state.is_shutting_down:
            return HealthCheck(
                name="gateway",
                status=HealthStatusLevel.UNHEALTHY,
                message="Gateway is shutting down"
            )

        return HealthCheck(
            name="gateway",
            status=HealthStatusLevel.HEALTHY,
            message="Gateway running"
        )

    async def _check_channels(self) -> List[HealthCheck]:
        """检查渠道状态"""
        checks = []

        if not self.state.channel_manager or not self.state.channel_manager.channels:
            return [HealthCheck(
                name="channels",
                status=HealthStatusLevel.DEGRADED,
                message="No channels registered"
            )]

        for name, adapter in self.state.channel_manager.channels.items():
            if adapter._running:
                checks.append(HealthCheck(
                    name=f"channel:{name}",
                    status=HealthStatusLevel.HEALTHY,
                    message="Connected"
                ))
            else:
                checks.append(HealthCheck(
                    name=f"channel:{name}",
                    status=HealthStatusLevel.UNHEALTHY,
                    message="Not running"
                ))

        return checks

    async def _check_agent(self) -> HealthCheck:
        """检查 Agent 连接"""
        return HealthCheck(
            name="agent",
            status=HealthStatusLevel.HEALTHY,
            message="Agent context available"
        )
```

### 4.4 通信协议

**文件**: `python/gateway/protocol.py`

```python
"""
Gateway 通信协议

定义网关与客户端之间的消息格式。
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional, Dict
from enum import Enum


class EventType(Enum):
    """事件类型"""
    # 连接事件
    HELLO = "hello"
    PING = "ping"
    PONG = "pong"

    # 系统事件
    SHUTDOWN = "shutdown"
    CONFIG_RELOAD = "config_reload"

    # Agent 事件
    AGENT_START = "agent_start"
    AGENT_CHUNK = "agent_chunk"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"

    # 渠道事件
    CHANNEL_MESSAGE = "channel_message"
    CHANNEL_STATUS = "channel_status"

    # 状态事件
    PRESENCE = "presence"
    TICK = "tick"


@dataclass
class GatewayEvent:
    """网关事件"""
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    seq: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "payload": self.payload,
            "seq": self.seq,
            "timestamp": self.timestamp.isoformat(),
        })

    @classmethod
    def from_json(cls, data: str) -> "GatewayEvent":
        obj = json.loads(data)
        return cls(
            type=EventType(obj["type"]),
            payload=obj.get("payload", {}),
            seq=obj.get("seq"),
            timestamp=datetime.fromisoformat(obj["timestamp"]) if "timestamp" in obj else datetime.now(),
        )


@dataclass
class GatewayRequest:
    """网关请求"""
    id: str
    method: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "type": "req",
            "id": self.id,
            "method": self.method,
            "params": self.params,
        })


@dataclass
class GatewayResponse:
    """网关响应"""
    id: str
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        result = {
            "type": "res",
            "id": self.id,
            "ok": self.ok,
        }
        if self.ok:
            result["payload"] = self.payload
        else:
            result["error"] = self.error
        return json.dumps(result)
```

### 4.5 热重载行为矩阵

**热重载支持的变更**:

| 配置项 | 热重载行为 | 影响 |
|--------|----------|------|
| `whitelist` | ✅ 即时生效 | 新消息立即验证 |
| `enabled: false→true` | ✅ 启动渠道 | 无中断 |
| `enabled: true→false` | ⚠️ 优雅停止 | 等待当前对话完成 |
| `require_mention` | ✅ 即时生效 | 新消息立即应用 |
| `token` | ❌ 需重启 | 必须重新认证 |
| `port` | ❌ 需重启 | 需重新绑定端口 |

---

## 6. 渠道适配器

### 5.1 消息模型 (增强版)

**文件**: `python/channels/base.py`

```python
"""
渠道适配器基类和消息模型 (V4 增强版)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable, Awaitable
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod
import asyncio


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"


@dataclass
class Attachment:
    """附件模型 (增强版)"""
    type: MessageType
    url: Optional[str] = None
    data: Optional[bytes] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None  # 文件大小 (bytes)
    
    @property
    def is_large(self) -> bool:
        """是否为大文件 (>10MB)"""
        return self.size and self.size > 10 * 1024 * 1024


@dataclass
class InboundMessage:
    """入站消息 (用户 → Agent)"""
    channel: str
    channel_user_id: str
    channel_chat_id: str
    content: str
    message_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    attachments: List[Attachment] = field(default_factory=list)
    is_group: bool = False
    reply_to_id: Optional[str] = None
    user_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """出站消息 (Agent → 用户)"""
    content: str
    attachments: List[Attachment] = field(default_factory=list)
    parse_mode: str = "markdown"
    reply_to_id: Optional[str] = None


@dataclass
class ChannelCapabilities:
    """渠道能力声明"""
    supports_markdown: bool = True
    supports_html: bool = False
    supports_reactions: bool = False
    supports_threads: bool = False
    supports_edit: bool = True
    supports_delete: bool = True
    max_message_length: int = 4096
    supports_attachments: bool = True
    supports_voice: bool = False
    # 新增: 流式响应相关
    supports_streaming_edit: bool = False  # 是否支持编辑消息实现流式
    edit_rate_limit_ms: int = 1000  # 编辑消息速率限制


MessageHandler = Callable[[InboundMessage], Awaitable[OutboundMessage]]


class ChannelAdapter(ABC):
    """渠道适配器抽象基类 (V4 增强版)"""

    def __init__(self, config: dict, account_id: str = "default"):
        self.config = config
        self.account_id = account_id
        self.name = self.__class__.__name__
        self._handler: Optional[MessageHandler] = None
        self._running = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_base_delay = 1.0
        self._max_reconnect_delay = 300  # 🆕 最大重连延迟 5 分钟

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilities:
        pass

    def on_message(self, handler: MessageHandler):
        self._handler = handler

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def send(self, chat_id: str, message: OutboundMessage):
        pass

    async def handle(self, message: InboundMessage) -> OutboundMessage:
        if self._handler:
            return await self._handler(message)
        return OutboundMessage(content="Handler not configured")

    # 🆕 错误恢复方法
    async def reconnect(self) -> bool:
        """带指数退避的重连"""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            return False
        
        # 🆕 添加延迟上限，避免过长等待
        delay = min(
            self._reconnect_base_delay * (2 ** self._reconnect_attempts),
            self._max_reconnect_delay
        )
        self._reconnect_attempts += 1
        
        await asyncio.sleep(delay)
        
        try:
            await self.stop()
            await self.start()
            self._reconnect_attempts = 0
            return True
        except Exception:
            return False

    async def handle_rate_limit(self, retry_after: float):
        """处理速率限制"""
        await asyncio.sleep(retry_after)

    def reset_reconnect_counter(self):
        """重置重连计数器"""
        self._reconnect_attempts = 0
```

### 5.2 渠道管理器

**文件**: `python/channels/manager.py`

```python
"""
渠道管理器

负责:
- 渠道注册和生命周期管理
- 消息路由
- 多账号支持
"""

import asyncio
import logging
from typing import Dict, Optional, List
from .base import ChannelAdapter, InboundMessage, OutboundMessage

logger = logging.getLogger("channels.manager")


class ChannelManager:
    """渠道管理器"""

    def __init__(self, agent_bridge, security_manager=None, metrics=None):
        """
        初始化渠道管理器

        Args:
            agent_bridge: AgentBridge 桥接层
            security_manager: 安全管理器
            metrics: 指标收集器
        """
        self.agent_bridge = agent_bridge
        self.security_manager = security_manager
        self.metrics = metrics
        self.channels: Dict[str, ChannelAdapter] = {}

    def register(self, name: str, adapter: ChannelAdapter):
        """注册渠道"""
        adapter.on_message(self._process_message)
        self.channels[name] = adapter
        logger.info(f"Registered channel: {name}")

    def unregister(self, name: str):
        """注销渠道"""
        if name in self.channels:
            del self.channels[name]
            logger.info(f"Unregistered channel: {name}")

    def get_channel(self, name: str) -> Optional[ChannelAdapter]:
        """获取渠道"""
        return self.channels.get(name)

    def list_channels(self) -> Dict[str, dict]:
        """列出所有渠道"""
        return {
            name: {
                "type": adapter.__class__.__name__,
                "account_id": adapter.account_id,
                "running": adapter._running,
                "capabilities": adapter.capabilities.__dict__,
            }
            for name, adapter in self.channels.items()
        }

    async def start_all(self):
        """启动所有渠道 (并发)"""
        if not self.channels:
            logger.warning("No channels to start")
            return

        # 使用 gather 并发启动，但捕获单个失败
        results = await asyncio.gather(
            *[self._start_channel(name, ch) for name, ch in self.channels.items()],
            return_exceptions=True
        )

        # 记录启动结果
        for (name, _), result in zip(self.channels.items(), results):
            if isinstance(result, Exception):
                logger.error(f"Failed to start channel {name}: {result}")

    async def _start_channel(self, name: str, adapter: ChannelAdapter):
        """启动单个渠道"""
        try:
            await adapter.start()
            adapter._running = True
            logger.info(f"Started channel: {name}")
        except Exception as e:
            adapter._running = False
            raise e

    async def stop_all(self):
        """停止所有渠道"""
        await asyncio.gather(
            *[self._stop_channel(name, ch) for name, ch in self.channels.items()],
            return_exceptions=True
        )

    async def _stop_channel(self, name: str, adapter: ChannelAdapter):
        """停止单个渠道"""
        try:
            await adapter.stop()
            adapter._running = False
            logger.info(f"Stopped channel: {name}")
        except Exception as e:
            logger.error(f"Error stopping channel {name}: {e}")

    async def apply_config_change(self, new_config: dict):
        """应用配置变更"""
        channels_config = new_config.get("channels", {})

        for channel_name, channel_cfg in channels_config.items():
            full_name = f"{channel_name}:{channel_cfg.get('account_id', 'default')}"

            # 禁用渠道
            if not channel_cfg.get("enabled", False):
                if full_name in self.channels:
                    await self._stop_channel(full_name, self.channels[full_name])
                    self.unregister(full_name)

            # 更新白名单等配置
            if full_name in self.channels:
                self.channels[full_name].config = channel_cfg

        # 重载安全配置
        if self.security_manager:
            self.security_manager.reload_config(type('Config', (), {'channels': channels_config})())

        logger.info("Config change applied")

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage:
        """路由消息到 Agent"""
        import time
        start_time = time.time()

        # 安全检查
        if self.security_manager:
            if not self.security_manager.check_access(msg):
                return OutboundMessage(content="Access denied")
            if not self.security_manager.check_rate_limit(msg):
                return OutboundMessage(content="Rate limit exceeded")
            if not self.security_manager.validate_message(msg):
                return OutboundMessage(content="Invalid message")

        # 记录接收指标
        if self.metrics:
            self.metrics.record_message_received(msg.channel)

        try:
            # 通过 AgentBridge 处理消息
            response = await self.agent_bridge.process_message(
                channel=msg.channel,
                channel_user_id=msg.channel_user_id,
                channel_chat_id=msg.channel_chat_id,
                content=msg.content,
                user_name=msg.user_name,
                attachments=msg.attachments,
                metadata=msg.metadata,
            )

            # 记录发送指标
            if self.metrics:
                response_time = (time.time() - start_time) * 1000
                self.metrics.record_message_sent(msg.channel, response_time)

            return OutboundMessage(content=response)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            if self.metrics:
                self.metrics.record_error(msg.channel, str(e))
            return OutboundMessage(content=f"Error: {str(e)}")
```

### 5.3 Telegram 适配器

**文件**: `python/channels/telegram_adapter.py`

**依赖**: `pip install python-telegram-bot>=20.0`

```python
"""
Telegram Bot 适配器

功能:
- 文本消息收发
- 图片/文件支持
- 群聊 @提及检测
- 长消息自动分块
- 流式响应 (消息编辑)
"""

import logging
from typing import Optional
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from .base import (
    ChannelAdapter, ChannelCapabilities,
    InboundMessage, OutboundMessage, Attachment, MessageType
)

logger = logging.getLogger("channels.telegram")


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot 适配器"""

    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.token = config["token"]
        self.app: Optional[Application] = None

        # 配置选项
        self.require_mention_in_groups = config.get("require_mention_in_groups", True)
        self.allowed_users = config.get("whitelist", [])  # 用户白名单

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            supports_markdown=True,
            supports_html=True,
            supports_reactions=False,
            supports_threads=False,
            supports_edit=True,
            supports_delete=True,
            max_message_length=4096,
            supports_attachments=True,
            supports_voice=True,
            supports_streaming_edit=True,
            edit_rate_limit_ms=1500,  # Telegram 编辑限制较严格
        )

    async def start(self):
        """启动 Telegram Bot"""
        self.app = Application.builder().token(self.token).build()

        # 注册消息处理器
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._on_message
        ))
        self.app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self._on_document))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        self._running = True
        self.reset_reconnect_counter()
        logger.info(f"Telegram adapter started: {self.account_id}")

    async def stop(self):
        """停止 Telegram Bot"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        self._running = False
        logger.info(f"Telegram adapter stopped: {self.account_id}")

    async def send(self, chat_id: str, message: OutboundMessage):
        """发送消息"""
        if not self.app:
            raise RuntimeError("Telegram adapter not started")

        # 分块发送长消息 (Telegram 限制 4096 字符)
        content = message.content
        max_len = 4000  # 留一些余量

        for i in range(0, len(content), max_len):
            chunk = content[i:i + max_len]
            await self.app.bot.send_message(
                chat_id=int(chat_id),
                text=chunk,
                parse_mode="Markdown" if message.parse_mode == "markdown" else None
            )

        # 发送附件
        for att in message.attachments:
            if att.type == MessageType.IMAGE:
                await self.app.bot.send_photo(
                    chat_id=int(chat_id),
                    photo=att.url or att.data
                )
            elif att.type == MessageType.FILE:
                await self.app.bot.send_document(
                    chat_id=int(chat_id),
                    document=att.url or att.data,
                    filename=att.filename
                )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本消息"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)
        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)

    async def _on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理图片消息"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)

        # 获取最大尺寸的图片
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        msg.attachments.append(Attachment(
            type=MessageType.IMAGE,
            url=file.file_path
        ))

        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)

    async def _on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文件消息"""
        if not self._should_respond(update):
            return

        msg = self._convert(update)

        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)
        msg.attachments.append(Attachment(
            type=MessageType.FILE,
            url=file.file_path,
            filename=doc.file_name,
            mime_type=doc.mime_type,
            size=doc.file_size,
        ))

        response = await self.handle(msg)
        await self.send(msg.channel_chat_id, response)

    def _should_respond(self, update: Update) -> bool:
        """判断是否应该响应此消息"""
        message = update.message
        if not message:
            return False

        # 白名单检查
        if self.allowed_users:
            if message.from_user.id not in self.allowed_users:
                return False

        # 群聊中需要 @提及
        if message.chat.type in ["group", "supergroup"]:
            if self.require_mention_in_groups:
                bot_username = self.app.bot.username
                text = message.text or message.caption or ""
                if f"@{bot_username}" not in text:
                    return False

        return True

    def _convert(self, update: Update) -> InboundMessage:
        """转换 Telegram 消息为统一格式"""
        m = update.message

        # 移除 @mention
        text = m.text or m.caption or ""
        if self.app and self.app.bot.username:
            text = text.replace(f"@{self.app.bot.username}", "").strip()

        return InboundMessage(
            channel="telegram",
            channel_user_id=str(m.from_user.id),
            channel_chat_id=str(m.chat_id),
            content=text,
            message_id=str(m.message_id),
            is_group=m.chat.type in ["group", "supergroup"],
            user_name=m.from_user.username or m.from_user.first_name,
            metadata={
                "chat_type": m.chat.type,
                "chat_title": m.chat.title if m.chat.type != "private" else None,
            }
        )
```

**创建 Telegram Bot 步骤**:

1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot` 并按提示操作
3. 获取 Bot Token（格式如 `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`）
4. 可选：使用 `/setprivacy` 设置隐私模式

### 5.4 Discord 适配器 (线程安全修正版)

**文件**: `python/channels/discord_adapter.py`

> **V4.1 关键修正**: 使用 `asyncio.run_coroutine_threadsafe()` 替代不安全的跨线程 Future 传递

```python
"""
Discord Bot 适配器 (V4.1 线程安全修正版)

修正:
- ✅ 使用 run_coroutine_threadsafe 安全跨线程调用
- ✅ 使用 run_in_executor 避免阻塞 Discord 事件循环
- ✅ 正确管理各线程的事件循环
"""

import asyncio
import logging
import threading
from typing import Optional
import discord
from discord.ext import commands

from .base import (
    ChannelAdapter, ChannelCapabilities,
    InboundMessage, OutboundMessage, Attachment, MessageType
)

logger = logging.getLogger("channels.discord")


class DiscordAdapter(ChannelAdapter):
    """Discord Bot 适配器 (线程安全修正版)"""

    def __init__(self, config: dict, account_id: str = "default"):
        super().__init__(config, account_id)
        self.token = config["token"]
        self.respond_to_dms = config.get("respond_to_dms", True)
        self.require_mention = config.get("require_mention", True)
        self.allowed_guilds = config.get("allowed_guilds", [])

        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)

        # 线程通信
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._discord_loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        self._setup()

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            supports_markdown=True,
            supports_html=False,
            supports_reactions=True,
            supports_threads=True,
            supports_edit=True,
            supports_delete=True,
            max_message_length=2000,
            supports_attachments=True,
            supports_voice=False,
            supports_streaming_edit=True,
            edit_rate_limit_ms=1000,
        )

    def _setup(self):
        @self.bot.event
        async def on_ready():
            logger.info(f"Discord: Logged in as {self.bot.user}")
            self.reset_reconnect_counter()

        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author == self.bot.user:
                return
            if not self._should_respond(message):
                return

            inbound = self._convert(message)

            # ✅ 关键修正：使用 run_coroutine_threadsafe 在主线程处理
            future = asyncio.run_coroutine_threadsafe(
                self._handle_in_main_loop(inbound),
                self._main_loop
            )

            try:
                # ✅ 使用 run_in_executor 避免阻塞 Discord 事件循环
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: future.result(timeout=300)
                )
                await self._send_response(message.channel, response)
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                await message.channel.send("⚠️ 处理消息时出错")

        @self.bot.event
        async def on_disconnect():
            logger.warning("Discord disconnected, will reconnect...")

        @self.bot.event
        async def on_error(event, *args, **kwargs):
            logger.error(f"Discord error in {event}")

    async def _handle_in_main_loop(self, inbound: InboundMessage) -> OutboundMessage:
        """在主事件循环中处理消息（线程安全）"""
        return await self.handle(inbound)

    async def start(self):
        """启动 Discord Bot"""
        # ✅ 获取当前运行的事件循环（主线程）
        self._main_loop = asyncio.get_running_loop()
        self._discord_loop = asyncio.new_event_loop()

        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()

        self._running = True
        logger.info(f"Discord adapter started: {self.account_id}")

    def _run_in_thread(self):
        """独立线程运行 Discord 事件循环"""
        asyncio.set_event_loop(self._discord_loop)
        self._discord_loop.run_until_complete(self.bot.start(self.token))

    async def _process_message_queue(self):
        """主线程处理消息队列"""
        while self._running:
            try:
                if not self._message_queue.empty():
                    msg_id, inbound = self._message_queue.get_nowait()
                    
                    # 调用消息处理器
                    response = await self.handle(inbound)
                    
                    # 通过 Future 返回响应到 Discord 线程
                    if msg_id in self._response_futures:
                        future = self._response_futures[msg_id]
                        # 线程安全地设置结果
                        self._discord_loop.call_soon_threadsafe(
                            future.set_result, response
                        )
                
                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error processing message: {e}")

    async def _send_response(self, channel, message: OutboundMessage):
        """发送响应消息"""
        content = message.content
        max_len = 1900
        
        for i in range(0, len(content), max_len):
            chunk = content[i:i + max_len]
            await channel.send(chunk)

    async def stop(self):
        """停止 Discord Bot"""
        self._running = False
        if self.bot:
            await self.bot.close()
        if self._discord_loop:
            self._discord_loop.call_soon_threadsafe(self._discord_loop.stop)
        logger.info(f"Discord adapter stopped: {self.account_id}")

    async def send(self, chat_id: str, message: OutboundMessage):
        """发送消息到指定频道"""
        channel = self.bot.get_channel(int(chat_id))
        if channel:
            await self._send_response(channel, message)

    def _should_respond(self, message: discord.Message) -> bool:
        if isinstance(message.channel, discord.DMChannel):
            return self.respond_to_dms
        if self.allowed_guilds:
            if message.guild and message.guild.id not in self.allowed_guilds:
                return False
        if self.require_mention:
            if self.bot.user not in message.mentions:
                return False
        return True

    def _convert(self, message: discord.Message) -> InboundMessage:
        content = message.content
        if self.bot.user:
            content = content.replace(f"<@{self.bot.user.id}>", "").strip()
            content = content.replace(f"<@!{self.bot.user.id}>", "").strip()
        
        attachments = []
        for a in message.attachments:
            att_type = MessageType.IMAGE if a.content_type and a.content_type.startswith("image") else MessageType.FILE
            attachments.append(Attachment(
                type=att_type,
                url=a.url,
                filename=a.filename,
                mime_type=a.content_type,
                size=a.size,
            ))
        
        return InboundMessage(
            channel="discord",
            channel_user_id=str(message.author.id),
            channel_chat_id=str(message.channel.id),
            content=content,
            message_id=str(message.id),
            attachments=attachments,
            is_group=isinstance(message.channel, discord.TextChannel),
            user_name=message.author.name,
            metadata={
                "guild_id": str(message.guild.id) if message.guild else None,
                "guild_name": message.guild.name if message.guild else None,
            }
        )
```

---

## 7. 流式响应策略

### 6.1 策略定义

**文件**: `python/channels/streaming.py`

```python
"""
流式响应策略

根据渠道能力选择最佳的流式响应策略
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
from .base import ChannelCapabilities


class StreamingStrategy(Enum):
    """流式响应策略"""
    BUFFER_ALL = "buffer_all"      # 等待完成后发送
    EDIT_MESSAGE = "edit_message"  # 定期编辑消息
    TYPING_INDICATOR = "typing"    # 发送"正在输入"提示
    CHUNKED_MESSAGES = "chunked"   # 按段落分批发送


@dataclass
class StreamingConfig:
    """流式响应配置"""
    strategy: StreamingStrategy
    edit_interval_ms: int = 1000   # 编辑间隔
    chunk_size: int = 500          # 分块大小
    typing_timeout: int = 5        # 输入提示超时
    max_edits: int = 50            # 最大编辑次数


class StreamingStrategySelector:
    """流式策略选择器"""
    
    @staticmethod
    def select(capabilities: ChannelCapabilities) -> StreamingConfig:
        """根据渠道能力选择最佳策略"""
        
        if capabilities.supports_streaming_edit:
            return StreamingConfig(
                strategy=StreamingStrategy.EDIT_MESSAGE,
                edit_interval_ms=max(capabilities.edit_rate_limit_ms, 1000),
            )
        else:
            return StreamingConfig(
                strategy=StreamingStrategy.BUFFER_ALL,
            )
    
    @staticmethod
    def get_strategy_for_channel(channel: str) -> StreamingConfig:
        """获取渠道专用策略"""
        strategies = {
            "telegram": StreamingConfig(
                strategy=StreamingStrategy.EDIT_MESSAGE,
                edit_interval_ms=1500,  # Telegram 编辑限制较严格
                max_edits=30,
            ),
            "discord": StreamingConfig(
                strategy=StreamingStrategy.EDIT_MESSAGE,
                edit_interval_ms=1000,
                max_edits=50,
            ),
            "email": StreamingConfig(
                strategy=StreamingStrategy.BUFFER_ALL,  # Email 不支持流式
            ),
        }
        return strategies.get(channel, StreamingConfig(strategy=StreamingStrategy.BUFFER_ALL))
```

### 6.2 流式响应处理器

```python
class StreamingHandler:
    """流式响应处理器"""
    
    def __init__(self, config: StreamingConfig, send_func: Callable):
        self.config = config
        self.send_func = send_func
        self._buffer = ""
        self._message_id: Optional[str] = None
        self._edit_count = 0
        self._last_edit_time = 0
    
    async def handle_chunk(self, chunk: str, full: str):
        """处理流式响应块"""
        if self.config.strategy == StreamingStrategy.BUFFER_ALL:
            self._buffer = full  # 仅缓存
        
        elif self.config.strategy == StreamingStrategy.EDIT_MESSAGE:
            import time
            now = time.time() * 1000
            
            if self._edit_count >= self.config.max_edits:
                self._buffer = full
                return
            
            if now - self._last_edit_time >= self.config.edit_interval_ms:
                await self._edit_or_send(full)
                self._last_edit_time = now
                self._edit_count += 1
    
    async def finalize(self) -> str:
        """完成流式响应"""
        if self._buffer:
            await self._edit_or_send(self._buffer, final=True)
        return self._buffer
    
    async def _edit_or_send(self, content: str, final: bool = False):
        """编辑或发送消息"""
        # 实现依赖具体渠道
        await self.send_func(content, self._message_id, final)
```

---

## 8. 错误恢复与监控

### 7.1 监控指标收集器

**文件**: `python/gateway/metrics.py`

```python
"""
监控指标收集器
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Optional
import time


@dataclass
class ChannelMetrics:
    """渠道运行指标"""
    messages_received: int = 0
    messages_sent: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    last_activity: Optional[datetime] = None
    total_response_time_ms: float = 0.0
    reconnect_count: int = 0
    
    @property
    def average_response_time_ms(self) -> float:
        if self.messages_sent == 0:
            return 0.0
        return self.total_response_time_ms / self.messages_sent


class MetricsCollector:
    """指标收集器"""

    def __init__(self):
        self._metrics: Dict[str, ChannelMetrics] = {}
        self._start_time = datetime.now()

    def _ensure_channel(self, channel: str):
        if channel not in self._metrics:
            self._metrics[channel] = ChannelMetrics()

    def record_message_received(self, channel: str):
        self._ensure_channel(channel)
        self._metrics[channel].messages_received += 1
        self._metrics[channel].last_activity = datetime.now()

    def record_message_sent(self, channel: str, response_time_ms: float):
        self._ensure_channel(channel)
        self._metrics[channel].messages_sent += 1
        self._metrics[channel].total_response_time_ms += response_time_ms
        self._metrics[channel].last_activity = datetime.now()

    def record_error(self, channel: str, error: str):
        self._ensure_channel(channel)
        self._metrics[channel].errors += 1
        self._metrics[channel].last_error = error

    def record_reconnect(self, channel: str):
        self._ensure_channel(channel)
        self._metrics[channel].reconnect_count += 1

    def get_channel_metrics(self, channel: str) -> Optional[ChannelMetrics]:
        return self._metrics.get(channel)

    def get_summary(self) -> Dict:
        return {
            "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            "channels": {
                name: {
                    **asdict(m),
                    "average_response_time_ms": m.average_response_time_ms,
                    "last_activity": m.last_activity.isoformat() if m.last_activity else None,
                }
                for name, m in self._metrics.items()
            }
        }
```

---

## 9. 安全模块

**文件**: `python/channels/security.py`

```python
"""
渠道安全模块
"""

import time
import logging
from typing import Dict, Set, Optional
from dataclasses import dataclass, field
from collections import defaultdict

from .base import InboundMessage

logger = logging.getLogger("channels.security")


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    max_requests: int = 10
    window_seconds: int = 60


@dataclass
class RateLimitState:
    """速率限制状态"""
    requests: list = field(default_factory=list)
    
    def is_limited(self, config: RateLimitConfig) -> bool:
        now = time.time()
        # 清理过期请求
        self.requests = [t for t in self.requests if now - t < config.window_seconds]
        if len(self.requests) >= config.max_requests:
            return True
        self.requests.append(now)
        return False


class SecurityManager:
    """安全管理器"""

    def __init__(self, config):
        self.config = config
        self._whitelists: Dict[str, Set[str]] = {}
        self._blacklists: Dict[str, Set[str]] = {}
        self._rate_limits: Dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._rate_config = RateLimitConfig()
        
        self._load_lists()

    def _load_lists(self):
        """从配置加载白名单/黑名单"""
        channels = self.config.channels if hasattr(self.config, 'channels') else {}
        for channel_name, channel_cfg in channels.items():
            if isinstance(channel_cfg, dict):
                whitelist = channel_cfg.get("whitelist", [])
                if whitelist:
                    self._whitelists[channel_name] = set(str(u) for u in whitelist)
                blacklist = channel_cfg.get("blacklist", [])
                if blacklist:
                    self._blacklists[channel_name] = set(str(u) for u in blacklist)

    def check_access(self, message: InboundMessage) -> bool:
        """检查访问权限"""
        channel = message.channel
        user_id = message.channel_user_id
        
        # 黑名单检查
        if channel in self._blacklists:
            if user_id in self._blacklists[channel]:
                logger.warning(f"Blocked blacklisted user: {channel}:{user_id}")
                return False
        
        # 白名单检查
        if channel in self._whitelists:
            if user_id not in self._whitelists[channel]:
                logger.warning(f"Blocked non-whitelisted user: {channel}:{user_id}")
                return False
        
        return True

    def check_rate_limit(self, message: InboundMessage) -> bool:
        """检查速率限制"""
        key = f"{message.channel}:{message.channel_user_id}"
        state = self._rate_limits[key]
        
        if state.is_limited(self._rate_config):
            logger.warning(f"Rate limited: {key}")
            return False
        return True

    def validate_message(self, message: InboundMessage) -> bool:
        """验证消息"""
        # 内容长度检查
        if len(message.content) > 10000:
            logger.warning(f"Message too long from {message.channel}:{message.channel_user_id}")
            return False
        
        return True

    def sanitize_output(self, content: str) -> str:
        """清理输出内容"""
        # 移除潜在危险内容
        # 可扩展: XSS 防护等
        return content

    def reload_config(self, new_config):
        """重载配置"""
        self.config = new_config
        self._load_lists()
        logger.info("Security config reloaded")
```

---

## 10. 高级功能

### 9.1 远程访问

```yaml
# conf/gateway.yaml
gateway:
  host: "0.0.0.0"  # 允许远程访问
  port: 18900
  auth:
    token: "${GATEWAY_AUTH_TOKEN}"  # 必须设置
```

### 9.2 渠道专用模型配置

```yaml
channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    # 可选: 渠道专用模型
    model_override:
      chat_model: "gpt-4"
      utility_model: "gpt-3.5-turbo"
```

---

## 11. 部署与运维

### 10.1 完整配置文件

**文件**: `conf/gateway.yaml`

```yaml
# Agent Zero Gateway 配置 V4

gateway:
  host: "127.0.0.1"
  port: 18900
  auth:
    token: "${GATEWAY_AUTH_TOKEN}"
  hot_reload: true
  verbose: false

channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    account_id: "main"
    require_mention_in_groups: true
    whitelist: []
    rate_limit:
      max_requests: 10
      window_seconds: 60

  discord:
    enabled: true
    token: "${DISCORD_BOT_TOKEN}"
    account_id: "main"
    respond_to_dms: true
    require_mention: true
    allowed_guilds: []
```

### 10.2 统一启动入口 (V4.1 推荐)

> **关键**: 使用单进程架构，Gateway 和 Web UI 在同一进程中运行，共享 `AgentContext._contexts`

**文件**: `run_all.py`

```python
#!/usr/bin/env python
"""
Agent Zero 统一启动入口 (V4.1)

单进程并行架构：
- Web UI (Flask) 在主线程运行
- Gateway (FastAPI/uvicorn) 在后台线程运行
- 共享 AgentContext._contexts 内存字典
"""

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("agent-zero")


def run_gateway_in_thread(host: str, port: int, log_level: str):
    """在独立线程中运行 Gateway"""
    import asyncio
    import uvicorn

    # 创建新的事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    config = uvicorn.Config(
        "python.gateway.server:app",
        host=host,
        port=port,
        log_level=log_level,
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    try:
        loop.run_until_complete(server.serve())
    except Exception as e:
        logger.error(f"Gateway error: {e}")
    finally:
        loop.close()


def main():
    parser = argparse.ArgumentParser(
        description="Agent Zero - Web UI + Gateway 统一启动"
    )

    # Web UI 参数
    parser.add_argument("--ui-host", default="0.0.0.0", help="Web UI bind host")
    parser.add_argument("--ui-port", type=int, default=50001, help="Web UI port")

    # Gateway 参数
    parser.add_argument("--gateway-host", default="127.0.0.1", help="Gateway bind host")
    parser.add_argument("--gateway-port", type=int, default=18900, help="Gateway port")
    parser.add_argument("--gateway-config", default="conf/gateway.yaml", help="Gateway config")

    # 通用参数
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--gateway-only", action="store_true", help="Only run Gateway")
    parser.add_argument("--ui-only", action="store_true", help="Only run Web UI")

    args = parser.parse_args()

    # 设置环境变量
    os.environ["GATEWAY_CONFIG_PATH"] = args.gateway_config
    os.environ["GATEWAY_PORT"] = str(args.gateway_port)
    os.environ["GATEWAY_HOST"] = args.gateway_host

    log_level = "debug" if args.verbose else "info"

    if args.gateway_only:
        # 仅运行 Gateway
        logger.info(f"Starting Gateway only on {args.gateway_host}:{args.gateway_port}")
        from python.gateway.server import run_gateway
        run_gateway(
            host=args.gateway_host,
            port=args.gateway_port,
            log_level=log_level,
        )
        return

    if args.ui_only:
        # 仅运行 Web UI
        logger.info(f"Starting Web UI only on {args.ui_host}:{args.ui_port}")
        from run_ui import app
        app.run(host=args.ui_host, port=args.ui_port)
        return

    # 同时运行 Gateway 和 Web UI
    logger.info("=" * 60)
    logger.info("Agent Zero - 单进程并行架构启动")
    logger.info("=" * 60)
    logger.info(f"Web UI:  http://{args.ui_host}:{args.ui_port}")
    logger.info(f"Gateway: http://{args.gateway_host}:{args.gateway_port}")
    logger.info("AgentContext: 共享内存模式")
    logger.info("=" * 60)

    # 启动 Gateway 线程
    gateway_thread = threading.Thread(
        target=run_gateway_in_thread,
        args=(args.gateway_host, args.gateway_port, log_level),
        daemon=True,
        name="GatewayThread"
    )
    gateway_thread.start()
    logger.info("Gateway thread started")

    # 等待 Gateway 启动
    time.sleep(1)

    # 在主线程运行 Web UI
    try:
        from run_ui import app
        logger.info("Starting Web UI in main thread...")
        app.run(host=args.ui_host, port=args.ui_port, threaded=True)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Web UI error: {e}")


if __name__ == "__main__":
    main()
```

**使用方式**:

```bash
# 同时启动 Web UI 和 Gateway (推荐)
python run_all.py

# 自定义端口
python run_all.py --ui-port 8080 --gateway-port 8081

# 仅启动 Gateway
python run_all.py --gateway-only

# 仅启动 Web UI
python run_all.py --ui-only

# 详细日志
python run_all.py -v
```

### 10.3 独立启动脚本

**文件**: `run_gateway.py`

```python
#!/usr/bin/env python
"""Agent Zero Gateway 启动入口"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Agent Zero Gateway")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", "-p", type=int, default=18900, help="Bind port")
    parser.add_argument("--config", "-c", default="conf/gateway.yaml", help="Config file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev)")
    args = parser.parse_args()

    os.environ["GATEWAY_CONFIG_PATH"] = args.config
    os.environ["GATEWAY_PORT"] = str(args.port)
    os.environ["GATEWAY_HOST"] = args.host

    from python.gateway.server import run_gateway
    run_gateway(
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if args.verbose else "info",
    )


if __name__ == "__main__":
    main()
```

### 11.3 Docker 部署（推荐）

> **推荐方式**：开发和生产都使用 Docker，确保环境一致性。

#### 开发环境 docker-compose.yml

```yaml
version: "3.8"

services:
  agent-zero:
    build: .
    container_name: agent-zero-dev
    ports:
      - "50001:50001"   # Web UI
      - "18900:18900"   # Gateway
    volumes:
      # 挂载代码目录，修改后立即生效
      - .:/a0
    env_file:
      - .env
    environment:
      - PYTHONDONTWRITEBYTECODE=1
      - DOCKER_CONTAINER=1
    working_dir: /a0
    command: python run_all.py --ui-host 0.0.0.0 --gateway-host 0.0.0.0
    restart: unless-stopped

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18900/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

#### 生产环境 docker-compose.prod.yml

```yaml
version: "3.8"

services:
  agent-zero:
    image: agent-zero:latest
    container_name: agent-zero-prod
    ports:
      - "50001:50001"
      - "18900:18900"
    volumes:
      # 只挂载数据目录，不挂载代码
      - ./data:/a0/data
      - ./memory:/a0/memory
      - ./knowledge:/a0/knowledge
      - ./conf:/a0/conf:ro
      - ./logs:/a0/logs
    env_file:
      - .env.prod
    environment:
      - DOCKER_CONTAINER=1
    working_dir: /a0
    command: python run_all.py --ui-host 0.0.0.0 --gateway-host 0.0.0.0
    restart: always

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18900/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

#### 常用 Docker 命令

```bash
# 开发环境
docker-compose up -d                    # 启动
docker-compose logs -f                  # 查看日志
docker-compose exec agent-zero bash     # 进入容器
docker-compose down                     # 停止

# 生产环境
docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml logs -f

# 在容器内执行命令
docker-compose exec agent-zero pytest tests/ -v
docker-compose exec agent-zero curl http://localhost:18900/api/health
```

### 11.4 CLI 管理命令

在容器内执行：

```bash
# 查看状态
curl http://localhost:18900/api/status

# 健康检查
curl http://localhost:18900/api/health

# 列出渠道
curl http://localhost:18900/api/channels

# 获取监控指标
curl http://localhost:18900/api/metrics

# 重载配置
curl -X POST http://localhost:18900/api/reload \
  -H "Authorization: Bearer your_token"
```

---

## 12. 测试与验收

### 11.1 验收标准

| 功能 | 标准 | 测试方法 |
|------|------|----------|
| Gateway 启动 | 10秒内就绪 | 脚本 |
| AgentBridge | 消息正确路由到 Agent | 单元测试 |
| 流式响应 | Telegram/Discord 编辑消息正常 | 手动 |
| 错误恢复 | 断线后自动重连 | kill -9 测试 |
| 安全模块 | 白名单/速率限制生效 | 手动 |
| 监控指标 | /api/metrics 返回正确数据 | curl |
| 会话共享 | Web UI 和渠道共享会话 | 手动 |
| 长时间运行 | 24小时稳定 | 监控 |

---

## 附录

### A. 依赖清单

```
# requirements-gateway.txt (V4.1 精确版本锁定)

# 核心框架 - 锁定主版本避免 breaking changes
fastapi>=0.100.0,<1.0.0
uvicorn[standard]>=0.23.0,<1.0.0
websockets>=11.0,<13.0

# 配置管理
pyyaml>=6.0,<7.0
python-dotenv>=1.0,<2.0
watchdog>=3.0,<5.0

# 渠道适配器 - 锁定主版本
python-telegram-bot>=20.0,<21.0
discord.py>=2.0,<3.0

# HTTP 客户端
httpx>=0.24.0,<1.0.0

# 可选：共享存储后端（分布式部署时使用）
# redis>=4.5.0,<6.0
```

### B. 环境变量

```bash
# .env 示例

# Gateway 配置
GATEWAY_PORT=18900
GATEWAY_HOST=127.0.0.1
GATEWAY_AUTH_TOKEN=your_secret_token

# Telegram Bot
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Discord Bot
DISCORD_BOT_TOKEN=your_discord_bot_token
```

### C. 更新日志

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 3.0 | 2026-02-01 | 完整代码实现 |
| 4.0 | 2026-02-01 | 并行共存架构、AgentBridge、流式策略、安全模块、监控指标 |
| **4.1** | **2026-02-01** | **单进程架构、Discord 线程安全修正、流式响应集成、统一启动入口、精确版本锁定** |

---

> **文档维护者**: AI Assistant
> **最后更新**: 2026-02-01
