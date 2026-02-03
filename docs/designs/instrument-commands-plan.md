# Agent Zero Instruments 自动命令开发计划

> **版本**: 1.0  
> **创建日期**: 2026-01-30  
> **目标**: 为 Instruments 添加 `/斜杠命令` 自动注册能力

---

## 1. 功能概述

### 1.1 目标

让用户可以通过 `/命令` 直接触发 Instrument，跳过 LLM 推理，实现：
- **更快**: 直接执行，无需等待 LLM 思考
- **更省**: 减少 Token 消耗
- **更准**: 避免 LLM 误解用户意图

### 1.2 使用效果

```
用户输入: /analyze_stock 贵州茅台

↓ 系统识别为命令

直接调用 instruments/custom/stock_analysis/
按照 stock_analysis.md 中的 Solution 执行
```

---

## 2. 设计方案

### 2.1 Instrument 配置格式

在现有 `.md` 文件顶部添加 YAML Frontmatter：

```markdown
---
command: analyze_stock           # 命令名 (不含 /)
description: 分析股票基本面      # 命令描述
args: symbol                     # 参数名
---

# Problem
分析一只股票的基本面和技术面

# Solution
1. 使用参数 {{symbol}} 作为股票代码
2. 调用 get_stock_info 获取基本信息
...
```

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                        消息处理流程                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  用户消息                                                           │
│      │                                                              │
│      ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │            CommandRouter (新增)                              │   │
│  │  1. 检查是否以 / 开头                                        │   │
│  │  2. 查找匹配的 Instrument 命令                               │   │
│  │  3. 匹配成功 → 直接执行                                      │   │
│  │  4. 匹配失败 → 继续正常流程                                  │   │
│  └──────────────────────────────┬──────────────────────────────┘   │
│                                 │                                   │
│         ┌───────────────────────┼───────────────────────┐          │
│         ▼                       ▼                       ▼          │
│  ┌─────────────┐      ┌─────────────────┐      ┌─────────────┐    │
│  │ 命令执行器  │      │  正常 Agent 流程 │      │  内置命令   │    │
│  │ (Instrument)│      │   (LLM 推理)    │      │ (/help等)  │    │
│  └─────────────┘      └─────────────────┘      └─────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 实现模块

### 3.1 模块 1: Frontmatter 解析器

**文件**: `python/helpers/instrument_parser.py`

```python
import re
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List

@dataclass
class InstrumentCommand:
    """Instrument 命令定义"""
    name: str                          # 命令名
    description: str                   # 描述
    args: Optional[str] = None         # 参数名
    instrument_path: Path = None       # instrument 目录路径
    content: str = ""                  # markdown 内容

FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)

def parse_instrument_frontmatter(md_path: Path) -> Optional[InstrumentCommand]:
    """
    解析 instrument markdown 文件的 frontmatter
    
    Args:
        md_path: .md 文件路径
    
    Returns:
        InstrumentCommand 或 None (如果没有命令定义)
    """
    try:
        content = md_path.read_text(encoding='utf-8')
        match = FRONTMATTER_PATTERN.match(content)
        
        if not match:
            return None
        
        frontmatter = yaml.safe_load(match.group(1))
        
        if not frontmatter or 'command' not in frontmatter:
            return None
        
        # 移除 frontmatter 后的内容
        body = content[match.end():]
        
        return InstrumentCommand(
            name=frontmatter['command'],
            description=frontmatter.get('description', ''),
            args=frontmatter.get('args'),
            instrument_path=md_path.parent,
            content=body
        )
    except Exception as e:
        print(f"[InstrumentParser] Error parsing {md_path}: {e}")
        return None


def discover_instrument_commands(instruments_dir: Path) -> Dict[str, InstrumentCommand]:
    """
    扫描 instruments 目录，发现所有注册了命令的 instrument
    
    Args:
        instruments_dir: instruments 根目录
    
    Returns:
        命令名 -> InstrumentCommand 的映射
    """
    commands = {}
    
    for subdir in ['default', 'custom']:
        dir_path = instruments_dir / subdir
        if not dir_path.exists():
            continue
        
        for instrument_dir in dir_path.iterdir():
            if not instrument_dir.is_dir():
                continue
            
            # 查找 .md 文件
            for md_file in instrument_dir.glob('*.md'):
                cmd = parse_instrument_frontmatter(md_file)
                if cmd:
                    commands[cmd.name.lower()] = cmd
                    print(f"[InstrumentParser] Registered command: /{cmd.name}")
    
    return commands
```

---

### 3.2 模块 2: 命令路由器

**文件**: `python/helpers/command_router.py`

```python
import re
from typing import Optional, Tuple
from pathlib import Path
from .instrument_parser import InstrumentCommand, discover_instrument_commands

class CommandRouter:
    """
    命令路由器 - 识别并分发 /斜杠命令
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._commands = {}
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._commands = {}
            self._initialized = True
    
    def load_commands(self, instruments_dir: str = "instruments"):
        """加载所有 instrument 命令"""
        path = Path(instruments_dir)
        self._commands = discover_instrument_commands(path)
        print(f"[CommandRouter] Loaded {len(self._commands)} instrument commands")
    
    def parse_message(self, message: str) -> Tuple[Optional[InstrumentCommand], Optional[str]]:
        """
        解析消息，判断是否为命令
        
        Args:
            message: 用户消息
        
        Returns:
            (InstrumentCommand, args) 或 (None, None)
        """
        message = message.strip()
        
        if not message.startswith('/'):
            return None, None
        
        # 解析命令和参数
        parts = message[1:].split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        command = self._commands.get(cmd_name)
        return command, args
    
    def get_help_text(self) -> str:
        """生成帮助文本"""
        if not self._commands:
            return "没有注册的 instrument 命令。"
        
        lines = ["**可用的 Instrument 命令:**\n"]
        for name, cmd in sorted(self._commands.items()):
            arg_hint = f" <{cmd.args}>" if cmd.args else ""
            lines.append(f"- `/{name}{arg_hint}` - {cmd.description}")
        
        return "\n".join(lines)
    
    def list_commands(self) -> list:
        """返回命令列表 (用于渠道菜单注册)"""
        return [
            {"name": cmd.name, "description": cmd.description}
            for cmd in self._commands.values()
        ]


# 全局实例
router = CommandRouter()
```

---

### 3.3 模块 3: 命令执行器

**文件**: `python/helpers/command_executor.py`

```python
import re
from typing import Any
from .instrument_parser import InstrumentCommand

class CommandExecutor:
    """
    命令执行器 - 执行 instrument 命令
    """
    
    def __init__(self, agent):
        self.agent = agent
    
    async def execute(self, command: InstrumentCommand, args: str) -> str:
        """
        执行 instrument 命令
        
        Args:
            command: InstrumentCommand 定义
            args: 用户提供的参数
        
        Returns:
            执行结果
        """
        # 1. 替换参数占位符
        content = command.content
        if command.args and args:
            content = content.replace(f"{{{{{command.args}}}}}", args)
            content = content.replace(f"{{{{ {command.args} }}}}", args)
        
        # 2. 提取 Solution 部分
        solution = self._extract_solution(content)
        
        # 3. 构建执行 prompt
        prompt = f"""执行以下 Instrument 任务:

**命令**: /{command.name}
**参数**: {args or '无'}

**执行步骤**:
{solution}

请严格按照上述步骤执行，不要添加额外的解释或确认。"""
        
        # 4. 调用 Agent 执行
        # 这里可以选择：
        # - 直接发给 LLM 执行步骤
        # - 或者解析步骤后调用具体工具
        
        result = await self.agent.process_message(prompt)
        return result
    
    def _extract_solution(self, content: str) -> str:
        """提取 Solution 部分"""
        match = re.search(r'#\s*Solution\s*\n(.*?)(?:\n#|$)', content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return content


async def handle_command(agent, message: str) -> tuple[bool, str]:
    """
    处理可能的命令消息
    
    Args:
        agent: Agent 实例
        message: 用户消息
    
    Returns:
        (是否为命令, 执行结果)
    """
    from .command_router import router
    
    command, args = router.parse_message(message)
    
    if command is None:
        return False, ""
    
    # 特殊命令: /help
    if message.strip().lower() in ['/help', '/commands']:
        return True, router.get_help_text()
    
    # 执行 instrument 命令
    executor = CommandExecutor(agent)
    result = await executor.execute(command, args)
    
    return True, result
```

---

### 3.4 集成到 Agent

**修改**: `agent.py`

```python
# 在消息处理入口添加命令检查

from python.helpers.command_executor import handle_command
from python.helpers.command_router import router

class Agent:
    def __init__(self, ...):
        # ... 现有初始化 ...
        
        # 加载 instrument 命令
        router.load_commands()
    
    async def message_loop(self, message: str):
        # 1. 先检查是否为命令
        is_command, result = await handle_command(self, message)
        
        if is_command:
            # 命令已执行，直接返回结果
            return result
        
        # 2. 继续正常的 Agent 流程
        # ... 现有逻辑 ...
```

---

## 4. 使用示例

### 4.1 创建带命令的 Instrument

```markdown
# instruments/custom/stock_analysis/stock_analysis.md

---
command: analyze_stock
description: 分析股票基本面和技术面
args: symbol
---

# Problem
分析一只股票的投资价值

# Solution
1. 获取股票 {{symbol}} 的基本信息
2. 调用 get_stock_info 工具
3. 调用 get_history_prices 获取30天历史数据
4. 计算关键指标 (PE, PB, 涨跌幅)
5. 给出投资建议

# Notes
- 确保股票代码格式正确
```

### 4.2 使用命令

```
用户: /analyze_stock 600519
Agent: [直接执行 stock_analysis instrument]
```

### 4.3 查看帮助

```
用户: /help
Agent: 
**可用的 Instrument 命令:**
- `/analyze_stock <symbol>` - 分析股票基本面和技术面
- `/youtube_download <url>` - 下载 YouTube 视频
```

---

## 5. 实施计划

```
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1: 核心实现 (1.5 天)                                          │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.1 (0.5天): Frontmatter 解析器                                │
│    - 创建 instrument_parser.py                                       │
│    - 实现 YAML frontmatter 解析                                      │
│    - 单元测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.2 (0.5天): 命令路由器                                        │
│    - 创建 command_router.py                                          │
│    - 实现命令发现和匹配                                               │
│    - 单元测试                                                        │
├──────────────────────────────────────────────────────────────────────┤
│  Step 1.3 (0.5天): 命令执行器                                        │
│    - 创建 command_executor.py                                        │
│    - 实现参数替换和执行                                               │
│    - 集成测试                                                        │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  Phase 2: 集成 (0.5 天)                                              │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.1: Agent 集成                                                │
│    - 修改 agent.py 添加命令检查                                       │
│    - 启动时加载命令                                                   │
├──────────────────────────────────────────────────────────────────────┤
│  Step 2.2: 渠道集成 (可选)                                           │
│    - Telegram: 注册 Bot Commands                                     │
│    - Discord: 注册 Slash Commands                                    │
└──────────────────────────────────────────────────────────────────────┘

总计: 2 天
```

---

## 6. 依赖

```
# 新增依赖
pyyaml>=6.0   # YAML 解析 (可能已有)
```

---

## 7. 测试清单

| 测试项 | 验证内容 |
|--------|----------|
| Frontmatter 解析 | 正确解析 YAML 头部 |
| 无 Frontmatter | 不影响现有 instrument |
| 命令匹配 | `/cmd` 正确匹配 |
| 参数传递 | `{{args}}` 正确替换 |
| /help 命令 | 列出所有可用命令 |
| 大小写 | `/CMD` = `/cmd` |
| 错误命令 | 降级到正常 Agent 流程 |

---

> **文档维护者**: AI Assistant  
> **最后更新**: 2026-01-30
