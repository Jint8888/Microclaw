# Gateway 代码改进 Walkthrough

> **版本**: 1.0
> **创建日期**: 2026-02-03
> **作者**: 浮浮酱 (AI Assistant)
> **目的**: 记录代码改进变更，便于回滚

---

## 📋 变更概览

| 变更ID | 文件 | 变更类型 | 说明 |
|--------|------|----------|------|
| CHG-001 | `telegram_adapter.py` | 重构 | 抽取公共方法减少重复代码 |
| CHG-002 | `discord_adapter.py` | 功能增强 | 添加附件发送支持 |
| CHG-003 | `config.py` | 修复 | 修复 get_event_loop() 弃用警告 |
| CHG-004 | `manager.py` | 功能增强 | 集成消息去重器 |
| CHG-005 | `manager.py` | 功能增强 | 集成错误处理器 |

---

## CHG-001: Telegram 适配器重构

### 变更文件
`python/channels/telegram_adapter.py`

### 变更原因
`_on_message`、`_on_photo`、`_on_document` 三个方法有大量重复的 typing indicator 和 placeholder 逻辑，违反 DRY 原则。

### 变更内容

#### 新增方法: `_send_attachments()`

```python
async def _send_attachments(self, chat_id: int, attachments: list):
    """Send attachment list to chat"""
    for att in attachments:
        try:
            if att.type == MessageType.IMAGE:
                await self.app.bot.send_photo(
                    chat_id=chat_id,
                    photo=att.local_path or att.url or att.data
                )
            elif att.type == MessageType.FILE:
                await self.app.bot.send_document(
                    chat_id=chat_id,
                    document=att.local_path or att.url or att.data,
                    filename=att.filename
                )
        except Exception as e:
            logger.error(f"Failed to send attachment: {e}")
```

#### 新增方法: `_handle_with_typing()`

```python
async def _handle_with_typing(
    self,
    update,
    context,
    msg: InboundMessage,
    placeholder_text: str
):
    """Unified message handling with typing indicator"""
    chat_id = int(msg.channel_chat_id)

    typing_task = asyncio.create_task(self._keep_typing(chat_id, context))

    try:
        placeholder_msg = await self.app.bot.send_message(
            chat_id=chat_id,
            text=placeholder_text,
            reply_to_message_id=int(msg.message_id)
        )

        response = await self.handle(msg)

        if response.content:
            await self._safe_edit_message(
                chat_id=chat_id,
                message_id=placeholder_msg.message_id,
                text=response.content
            )
        else:
            await self._safe_edit_message(
                chat_id=chat_id,
                message_id=placeholder_msg.message_id,
                text="(无响应内容)"
            )

        await self._send_attachments(chat_id, response.attachments)

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        try:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ 处理消息时出错: {str(e)[:200]}"
            )
        except Exception:
            pass
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
```

#### 简化后的 `_on_message`

```python
async def _on_message(self, update, context):
    """Handle text message with typing indicator and streaming response"""
    if not self._should_respond(update):
        return
    msg = self._convert(update)
    await self._handle_with_typing(update, context, msg, "🤔 思考中...")
```

### 回滚方法

恢复原始的 `_on_message`、`_on_photo`、`_on_document` 方法，删除新增的 `_send_attachments` 和 `_handle_with_typing` 方法。

---

## CHG-002: Discord 适配器附件发送

### 变更文件
`python/channels/discord_adapter.py`

### 变更原因
`_send_response` 方法只发送文本，没有处理 `OutboundMessage.attachments`。

### 变更内容

#### 修改方法: `_send_response()`

**原代码:**
```python
async def _send_response(self, channel, message: OutboundMessage):
    """Send response message"""
    content = message.content
    max_len = 1900

    for i in range(0, len(content), max_len):
        chunk = content[i:i + max_len]
        await channel.send(chunk)
```

**新代码:**
```python
async def _send_response(self, channel, message: OutboundMessage):
    """Send response message with attachments"""
    import discord
    import os

    content = message.content
    max_len = 1900

    for i in range(0, len(content), max_len):
        chunk = content[i:i + max_len]
        await channel.send(chunk)

    # Send attachments
    for att in message.attachments:
        try:
            if att.local_path and os.path.exists(att.local_path):
                await channel.send(file=discord.File(att.local_path))
            elif att.url:
                await channel.send(att.url)
        except Exception as e:
            logger.error(f"Failed to send Discord attachment: {e}")
```

### 回滚方法

删除附件发送相关代码，恢复原始的纯文本发送逻辑。

---

## CHG-003: Config 弃用警告修复

### 变更文件
`python/gateway/config.py`

### 变更原因
`asyncio.get_event_loop()` 在 Python 3.10+ 中已弃用，应使用 `asyncio.get_running_loop()`。

### 变更内容

#### 修改方法: `ConfigWatcher._on_change()`

**原代码 (第 212-217 行):**
```python
try:
    loop = asyncio.get_event_loop()
    self._debounce_task = loop.create_task(debounced_callback())
except RuntimeError:
    # No event loop running, skip
    pass
```

**新代码:**
```python
try:
    loop = asyncio.get_running_loop()
    self._debounce_task = loop.create_task(debounced_callback())
except RuntimeError:
    # No running event loop, try to run in new loop
    try:
        asyncio.run(debounced_callback())
    except Exception as e:
        logger.warning(f"Could not run config reload callback: {e}")
```

### 回滚方法

恢复使用 `asyncio.get_event_loop()`。

---

## CHG-004: 集成消息去重器

### 变更文件
`python/channels/manager.py`

### 变更原因
`deduplicator.py` 已实现但未在消息处理流程中使用，可能导致重复消息被处理。

### 变更内容

#### 修改 `__init__` 方法

**新增:**
```python
from python.gateway.deduplicator import MessageDeduplicator

def __init__(self, agent_bridge, security_manager=None, metrics=None):
    # ... existing code ...
    self.deduplicator = MessageDeduplicator(ttl_seconds=60, max_size=1000)
```

#### 修改 `_process_message` 方法

**新增去重检查 (在安全检查之前):**
```python
async def _process_message(self, msg: InboundMessage) -> OutboundMessage:
    """Route message to Agent"""
    start_time = time.time()

    # Message deduplication check
    if self.deduplicator.is_duplicate(msg.message_id, msg.channel):
        logger.debug(f"Duplicate message ignored: {msg.channel}:{msg.message_id}")
        return None

    # Security checks
    # ... rest of existing code ...
```

### 回滚方法

删除 `deduplicator` 相关导入和初始化，删除 `_process_message` 中的去重检查代码。

---

## CHG-005: 集成错误处理器

### 变更文件
`python/channels/manager.py`

### 变更原因
`errors.py` 已实现完整的错误分类和多语言支持，但代码中直接返回原始错误信息，对用户不友好。

### 变更内容

#### 新增导入

```python
from python.gateway.errors import error_handler
```

#### 修改 `_process_message` 异常处理

**原代码 (第 224-228 行):**
```python
except Exception as e:
    logger.error(f"Error processing message: {e}")
    if self.metrics:
        self.metrics.record_error(msg.channel, str(e))
    return OutboundMessage(content=f"⚠️ Error: {str(e)}")
```

**新代码:**
```python
except Exception as e:
    logger.error(f"Error processing message: {e}")
    if self.metrics:
        self.metrics.record_error(msg.channel, str(e))

    # Use error handler for user-friendly message
    user_message = error_handler.format_error(e, language="zh")
    return OutboundMessage(content=user_message)
```

### 回滚方法

恢复直接返回 `f"⚠️ Error: {str(e)}"` 的原始错误处理方式。

---

## 📁 备份文件

在修改前，建议备份以下文件：

```bash
# 创建备份目录
mkdir -p backups/gateway-improvement-2026-02-03

# 备份文件
cp python/channels/telegram_adapter.py backups/gateway-improvement-2026-02-03/
cp python/channels/discord_adapter.py backups/gateway-improvement-2026-02-03/
cp python/channels/manager.py backups/gateway-improvement-2026-02-03/
cp python/gateway/config.py backups/gateway-improvement-2026-02-03/
```

---

## 🔄 完整回滚命令

如需回滚所有变更：

```bash
# 从备份恢复
cp backups/gateway-improvement-2026-02-03/telegram_adapter.py python/channels/
cp backups/gateway-improvement-2026-02-03/discord_adapter.py python/channels/
cp backups/gateway-improvement-2026-02-03/manager.py python/channels/
cp backups/gateway-improvement-2026-02-03/config.py python/gateway/
```

或使用 Git：

```bash
# 查看变更
git diff python/channels/ python/gateway/config.py

# 回滚特定文件
git checkout HEAD -- python/channels/telegram_adapter.py
git checkout HEAD -- python/channels/discord_adapter.py
git checkout HEAD -- python/channels/manager.py
git checkout HEAD -- python/gateway/config.py
```

---

> **文档维护者**: 浮浮酱 (AI Assistant)
> **最后更新**: 2026-02-03
