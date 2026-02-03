# Gateway 图片附件功能 Walkthrough

## 功能概述

允许 Agent 返回的图片路径自动发送到 Telegram 机器人端显示，而不仅仅是文本 URL。

## 修改文件

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `python/channels/manager.py` | 修改 | 添加图片路径检测和附件转换 |

## 修改前代码 (manager.py:196-219)

```python
try:
    # Process attachments - convert to local paths
    attachment_paths = []
    for att in msg.attachments:
        if att.local_path:
            attachment_paths.append(att.local_path)

    # Process message via AgentBridge
    response = await self.agent_bridge.process_message(
        channel=msg.channel,
        channel_user_id=msg.channel_user_id,
        channel_chat_id=msg.channel_chat_id,
        content=msg.content,
        user_name=msg.user_name,
        attachments=attachment_paths,
        metadata=msg.metadata,
    )

    # Record send metrics
    if self.metrics:
        response_time = (time.time() - start_time) * 1000
        self.metrics.record_message_sent(msg.channel, response_time)

    return OutboundMessage(content=response)
```

## 修改后代码 (manager.py:196-240)

```python
try:
    # Process attachments - convert to local paths
    attachment_paths = []
    for att in msg.attachments:
        if att.local_path:
            attachment_paths.append(att.local_path)

    # Process message via AgentBridge
    response = await self.agent_bridge.process_message(
        channel=msg.channel,
        channel_user_id=msg.channel_user_id,
        channel_chat_id=msg.channel_chat_id,
        content=msg.content,
        user_name=msg.user_name,
        attachments=attachment_paths,
        metadata=msg.metadata,
    )

    # Record send metrics
    if self.metrics:
        response_time = (time.time() - start_time) * 1000
        self.metrics.record_message_sent(msg.channel, response_time)

    # Extract image attachments from response (Gateway only, does not affect WebUI)
    response_attachments = self._extract_image_attachments(response)

    return OutboundMessage(content=response, attachments=response_attachments)
```

## 新增方法 (_extract_image_attachments)

```python
def _extract_image_attachments(self, response: str) -> list:
    """
    Extract image paths from Agent response and convert to Attachment objects.

    This only affects Gateway channels (Telegram, Discord, etc.),
    WebUI communicates directly with Agent and is not affected.

    Supported patterns:
    - /a0/tmp/xxx.jpg
    - /a0/data/xxx.png
    - /git/agent-zero/tmp/xxx.gif
    - Docker container paths

    Returns:
        List of Attachment objects for detected images
    """
    import re
    import os
    from .base import Attachment, MessageType

    attachments = []

    # Image file extensions
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}

    # Path patterns to detect (Docker container paths)
    path_patterns = [
        r'(/a0/(?:tmp|data|downloads?|output|work)[^\s\"\'\)]*\.(?:jpg|jpeg|png|gif|webp|bmp))',
        r'(/git/agent-zero/(?:tmp|data|downloads?|output|work)[^\s\"\'\)]*\.(?:jpg|jpeg|png|gif|webp|bmp))',
        r'(/app/(?:tmp|data|downloads?|output|work)[^\s\"\'\)]*\.(?:jpg|jpeg|png|gif|webp|bmp))',
    ]

    found_paths = set()

    for pattern in path_patterns:
        matches = re.findall(pattern, response, re.IGNORECASE)
        found_paths.update(matches)

    for path in found_paths:
        # Verify file exists
        if os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in image_extensions:
                attachments.append(Attachment(
                    type=MessageType.IMAGE,
                    local_path=path,
                    filename=os.path.basename(path),
                ))
                logger.info(f"Extracted image attachment: {path}")

    return attachments
```

## 回滚步骤

如需回滚，执行以下操作：

### 1. 还原 manager.py

将 `_process_message` 方法的返回语句从：
```python
response_attachments = self._extract_image_attachments(response)
return OutboundMessage(content=response, attachments=response_attachments)
```

改回：
```python
return OutboundMessage(content=response)
```

### 2. 删除 `_extract_image_attachments` 方法

删除整个 `_extract_image_attachments` 方法定义。

### 3. 重启容器

```bash
docker-compose restart
```

## 影响范围

| 组件 | 是否受影响 | 说明 |
|------|------------|------|
| WebUI | 否 | WebUI 直接与 Agent 通信，不经过 ChannelManager |
| Telegram | 是 | 响应中的图片路径会自动作为图片发送 |
| Discord | 是 | 同上 |
| Email | 是 | 同上 |

## 测试方法

1. 重启容器：`docker-compose restart`
2. 在 Telegram 机器人发送请求，如 "下载这张图片 https://example.com/image.jpg"
3. 观察是否收到图片（而不仅仅是路径文本）

## 创建日期

2024-XX-XX (根据实际日期填写)
