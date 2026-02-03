# Agent Zero 浏览器控制系统开发计划

> **版本**: 1.0  
> **创建日期**: 2026-01-31  
> **优先级**: 🟡 中  
> **目标**: 为 Agent Zero 添加精细化浏览器控制能力，与现有 browser-use 模式互补

---

## 1. 功能概述

### 1.1 现状

Agent Zero 目前使用 `browser-use` 库，采用 **AI 自主执行模式**：
- ✅ 优点：自然语言描述任务，AI 自动完成
- ❌ 缺点：无法精确控制、无法复用登录状态

### 1.2 目标

引入 **精细控制模式**，实现：

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser Control Layer                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌─────────────────┐        ┌─────────────────┐            │
│   │  browser-use    │        │  精细控制模式    │            │
│   │  (AI 自主模式)   │   ←→   │  (手动控制模式)  │            │
│   └─────────────────┘        └─────────────────┘            │
│          ↓                           ↓                       │
│   自然语言任务              精确操作指令                       │
│   AI 决策执行              确定性执行                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 核心功能

### 2.1 功能清单

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 浏览器启动/停止 | P0 | 控制浏览器生命周期 |
| 标签页管理 | P0 | 打开、关闭、切换标签页 |
| 页面导航 | P0 | 访问 URL、前进后退 |
| 页面快照 | P0 | 获取 DOM 结构供 AI 分析 |
| 页面截图 | P0 | 全页面/元素截图 |
| 页面操作 | P0 | 点击、输入、滚动 |
| Profile 管理 | P1 | 隔离会话/复用登录 |
| 文件上传 | P1 | 处理文件选择对话框 |
| 对话框处理 | P1 | alert/confirm/prompt |
| PDF 导出 | P2 | 页面转 PDF |
| Cookie 管理 | P2 | 读写 Cookie |

---

## 3. 架构设计

### 3.1 模块结构

```
python/
├── helpers/
│   ├── browser_control/
│   │   ├── __init__.py
│   │   ├── manager.py          # 浏览器生命周期管理
│   │   ├── session.py          # 会话管理
│   │   ├── actions.py          # 页面操作
│   │   └── snapshot.py         # 页面快照
├── tools/
│   ├── browser_agent.py        # 现有 AI 自主模式
│   └── browser_control.py      # 新增精细控制模式
```

### 3.2 工具参数设计

```python
# browser_control 工具参数
{
    "action": "snapshot|screenshot|navigate|click|type|scroll|...",
    "profile": "default|chrome|custom",
    "targetId": "tab-xxx",
    "params": {
        # 各操作的具体参数
    }
}
```

---

## 4. 实现模块

### 4.1 模块 1: 浏览器管理器

**文件**: `python/helpers/browser_control/manager.py`

```python
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from typing import Optional, Dict, List
from dataclasses import dataclass, field
import asyncio

@dataclass
class BrowserSession:
    """浏览器会话"""
    browser: Browser
    context: BrowserContext
    pages: Dict[str, Page] = field(default_factory=dict)
    
    async def close(self):
        await self.context.close()
        await self.browser.close()

class BrowserManager:
    """
    浏览器管理器
    
    Usage:
        manager = BrowserManager()
        await manager.start()
        
        # 打开页面
        page = await manager.open_tab("https://example.com")
        
        # 获取快照
        snapshot = await manager.get_snapshot()
        
        # 执行操作
        await manager.click(selector="#button")
        
        await manager.stop()
    """
    
    def __init__(self):
        self._playwright = None
        self._session: Optional[BrowserSession] = None
        self._current_target: Optional[str] = None
    
    async def start(self, headless: bool = True, profile: str = "default") -> dict:
        """启动浏览器"""
        if self._session:
            return {"status": "already_running"}
        
        self._playwright = await async_playwright().start()
        
        browser = await self._playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        )
        
        self._session = BrowserSession(
            browser=browser,
            context=context
        )
        
        return {"status": "started", "headless": headless}
    
    async def stop(self) -> dict:
        """停止浏览器"""
        if not self._session:
            return {"status": "not_running"}
        
        await self._session.close()
        await self._playwright.stop()
        self._session = None
        self._playwright = None
        
        return {"status": "stopped"}
    
    async def get_status(self) -> dict:
        """获取状态"""
        if not self._session:
            return {"running": False}
        
        return {
            "running": True,
            "tabs": list(self._session.pages.keys()),
            "current_target": self._current_target
        }
    
    async def open_tab(self, url: str) -> dict:
        """打开新标签页"""
        self._ensure_running()
        
        page = await self._session.context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        
        target_id = f"tab-{len(self._session.pages)}"
        self._session.pages[target_id] = page
        self._current_target = target_id
        
        return {
            "targetId": target_id,
            "url": page.url,
            "title": await page.title()
        }
    
    async def close_tab(self, target_id: str = None) -> dict:
        """关闭标签页"""
        self._ensure_running()
        
        target = target_id or self._current_target
        if target and target in self._session.pages:
            page = self._session.pages.pop(target)
            await page.close()
            
            if self._current_target == target:
                self._current_target = next(iter(self._session.pages), None)
        
        return {"closed": target}
    
    async def list_tabs(self) -> List[dict]:
        """列出所有标签页"""
        self._ensure_running()
        
        tabs = []
        for target_id, page in self._session.pages.items():
            tabs.append({
                "targetId": target_id,
                "url": page.url,
                "title": await page.title()
            })
        return tabs
    
    def _ensure_running(self):
        if not self._session:
            raise RuntimeError("Browser not started. Call start() first.")
    
    def _get_page(self, target_id: str = None) -> Page:
        self._ensure_running()
        target = target_id or self._current_target
        if not target or target not in self._session.pages:
            raise ValueError(f"Tab not found: {target}")
        return self._session.pages[target]


# 全局单例
_browser_manager: Optional[BrowserManager] = None

def get_browser_manager() -> BrowserManager:
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager
```

### 4.2 模块 2: 页面操作

**文件**: `python/helpers/browser_control/actions.py`

```python
from playwright.async_api import Page
from typing import Optional, Dict, Any
import base64

class PageActions:
    """页面操作"""
    
    def __init__(self, page: Page):
        self.page = page
    
    async def navigate(self, url: str) -> dict:
        """导航到 URL"""
        await self.page.goto(url, wait_until="domcontentloaded")
        return {
            "url": self.page.url,
            "title": await self.page.title()
        }
    
    async def click(self, selector: str, timeout: int = 5000) -> dict:
        """点击元素"""
        await self.page.click(selector, timeout=timeout)
        return {"clicked": selector}
    
    async def type(self, selector: str, text: str, delay: int = 50) -> dict:
        """输入文本"""
        await self.page.fill(selector, text)
        return {"typed": len(text), "selector": selector}
    
    async def scroll(self, direction: str = "down", amount: int = 300) -> dict:
        """滚动页面"""
        delta = amount if direction == "down" else -amount
        await self.page.evaluate(f"window.scrollBy(0, {delta})")
        return {"scrolled": delta}
    
    async def screenshot(self, full_page: bool = False, selector: str = None) -> dict:
        """截图"""
        options = {"full_page": full_page}
        
        if selector:
            element = await self.page.query_selector(selector)
            if element:
                screenshot_bytes = await element.screenshot()
            else:
                raise ValueError(f"Element not found: {selector}")
        else:
            screenshot_bytes = await self.page.screenshot(**options)
        
        return {
            "base64": base64.b64encode(screenshot_bytes).decode(),
            "size": len(screenshot_bytes)
        }
    
    async def get_snapshot(self, max_chars: int = 50000) -> dict:
        """获取页面快照 (DOM 结构)"""
        # 获取简化的 DOM 结构
        snapshot = await self.page.evaluate("""
            () => {
                function getSnapshot(el, depth = 0) {
                    if (depth > 10) return null;
                    
                    const tag = el.tagName?.toLowerCase();
                    if (!tag || ['script', 'style', 'noscript'].includes(tag)) return null;
                    
                    const result = { tag };
                    
                    // 重要属性
                    if (el.id) result.id = el.id;
                    if (el.className) result.class = el.className;
                    if (el.href) result.href = el.href;
                    if (el.value) result.value = el.value;
                    
                    // 文本内容
                    if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3) {
                        result.text = el.textContent.trim().slice(0, 100);
                    }
                    
                    // 可交互标记
                    if (['a', 'button', 'input', 'select', 'textarea'].includes(tag)) {
                        result.interactive = true;
                    }
                    
                    // 子元素
                    const children = [];
                    for (const child of el.children) {
                        const snap = getSnapshot(child, depth + 1);
                        if (snap) children.push(snap);
                    }
                    if (children.length) result.children = children;
                    
                    return result;
                }
                return getSnapshot(document.body);
            }
        """)
        
        import json
        text = json.dumps(snapshot, ensure_ascii=False, indent=2)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        
        return {
            "url": self.page.url,
            "title": await self.page.title(),
            "snapshot": text
        }
    
    async def eval_js(self, script: str) -> Any:
        """执行 JavaScript"""
        return await self.page.evaluate(script)
```

### 4.3 模块 3: Browser Control 工具

**文件**: `python/tools/browser_control.py`

```python
from python.helpers.tool import Tool, Response
from python.helpers.browser_control.manager import get_browser_manager
from python.helpers.browser_control.actions import PageActions
from agent import Agent

class BrowserControl(Tool):
    """
    精细浏览器控制工具
    
    与 browser_agent (AI 自主模式) 互补，提供精确操作能力
    """
    
    async def execute(self, action: str, **kwargs):
        manager = get_browser_manager()
        
        # 浏览器生命周期
        if action == "start":
            return Response(
                message=str(await manager.start(
                    headless=kwargs.get("headless", True)
                )),
                break_loop=False
            )
        
        if action == "stop":
            return Response(
                message=str(await manager.stop()),
                break_loop=False
            )
        
        if action == "status":
            return Response(
                message=str(await manager.get_status()),
                break_loop=False
            )
        
        # 标签页管理
        if action == "open":
            url = kwargs.get("url", "about:blank")
            return Response(
                message=str(await manager.open_tab(url)),
                break_loop=False
            )
        
        if action == "close":
            return Response(
                message=str(await manager.close_tab(kwargs.get("targetId"))),
                break_loop=False
            )
        
        if action == "tabs":
            return Response(
                message=str(await manager.list_tabs()),
                break_loop=False
            )
        
        # 页面操作
        page = manager._get_page(kwargs.get("targetId"))
        actions = PageActions(page)
        
        if action == "navigate":
            return Response(
                message=str(await actions.navigate(kwargs["url"])),
                break_loop=False
            )
        
        if action == "click":
            return Response(
                message=str(await actions.click(kwargs["selector"])),
                break_loop=False
            )
        
        if action == "type":
            return Response(
                message=str(await actions.type(kwargs["selector"], kwargs["text"])),
                break_loop=False
            )
        
        if action == "scroll":
            return Response(
                message=str(await actions.scroll(
                    kwargs.get("direction", "down"),
                    kwargs.get("amount", 300)
                )),
                break_loop=False
            )
        
        if action == "screenshot":
            result = await actions.screenshot(
                full_page=kwargs.get("fullPage", False),
                selector=kwargs.get("selector")
            )
            return Response(
                message=f"Screenshot taken ({result['size']} bytes)",
                break_loop=False
            )
        
        if action == "snapshot":
            return Response(
                message=str(await actions.get_snapshot()),
                break_loop=False
            )
        
        return Response(
            message=f"Unknown action: {action}",
            break_loop=False
        )
```

---

## 5. 使用示例

### 5.1 精细控制模式

```
User: 打开百度，搜索"天气预报"，截图保存

Agent (使用 browser_control):
1. browser_control(action="start")
2. browser_control(action="open", url="https://baidu.com")
3. browser_control(action="type", selector="#kw", text="天气预报")
4. browser_control(action="click", selector="#su")
5. browser_control(action="screenshot", fullPage=True)
```

### 5.2 与 AI 模式配合

```
User: 帮我在淘宝搜索便宜的耳机

Agent:
1. 使用 browser_control 启动并打开淘宝
2. 切换到 browser_agent (AI 模式) 自动搜索和筛选
3. 返回 browser_control 截图保存结果
```

---

## 6. 实施计划

```
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: 基础功能 (2 天)                                            │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.1: BrowserManager 核心框架                                   │
│  Step 1.2: 基础页面操作 (navigate, click, type)                      │
│  Step 1.3: BrowserControl 工具集成                                   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  Phase 2: 高级功能 (2 天)                                            │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.1: 页面快照 (供 AI 分析)                                     │
│  Step 2.2: 截图功能                                                  │
│  Step 2.3: 多标签页管理                                              │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  Phase 3: Profile 和持久化 (1.5 天)                                  │
├──────────────────────────────────────────────────────────────────────┤
│  Step 3.1: Profile 管理 (复用登录状态)                               │
│  Step 3.2: Cookie 持久化                                             │
│  Step 3.3: 与 browser-use 模式切换                                   │
└──────────────────────────────────────────────────────────────────────┘

总计: 5.5 天
```

---

## 7. 依赖

```
# requirements.txt 新增
playwright>=1.40.0
```

```bash
# 安装浏览器
playwright install chromium
```

---

> **文档维护者**: AI Assistant  
> **最后更新**: 2026-01-31
