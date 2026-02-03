# Agent Zero 企业级功能参考文档

> **版本**: 1.0  
> **创建日期**: 2026-01-30  
> **优先级**: 🟢 低 (后续参考)  
> **说明**: 本文档整合安全审计、配置验证和 Gateway API 三个功能，供后续需要时参考

---

## 功能概览

| 功能 | 适用场景 | 复杂度 | 参考来源 |
|------|----------|--------|----------|
| 安全审计 | 生产部署、多用户 | 中 | OpenClaw `security/audit.ts` |
| 配置验证 | 复杂配置、插件系统 | 中 | OpenClaw `config/validation.ts` |
| Gateway API | 多节点、第三方集成 | 高 | OpenClaw `gateway/` |

---

## 1. 安全审计 (Security Audit)

### 1.1 功能描述

自动扫描系统配置和运行环境，发现潜在安全风险并给出修复建议。

### 1.2 检查项目

```python
class AuditSeverity(Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"

# 检查清单
AUDIT_CHECKS = {
    # 文件系统权限
    "fs.config.perms": "配置文件是否被他人可读/可写",
    "fs.state_dir.perms": "状态目录权限是否过于宽松",
    
    # 网络暴露
    "gateway.bind_no_auth": "Gateway 绑定非 loopback 但无认证",
    "gateway.tailscale_funnel": "Tailscale Funnel 公网暴露",
    
    # 渠道安全
    "channels.dm.open": "DM 对所有人开放",
    "channels.commands.unrestricted": "命令无访问控制",
    
    # 日志安全
    "logging.redact_off": "敏感信息脱敏已禁用",
    
    # 浏览器控制
    "browser.remote_cdp_http": "远程 CDP 使用 HTTP",
}
```

### 1.3 实现参考

```python
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path
import os
import stat

@dataclass
class AuditFinding:
    """审计发现"""
    check_id: str
    severity: str  # info, warn, critical
    title: str
    detail: str
    remediation: Optional[str] = None

@dataclass
class AuditReport:
    """审计报告"""
    timestamp: float
    findings: List[AuditFinding]
    
    @property
    def summary(self):
        return {
            "critical": len([f for f in self.findings if f.severity == "critical"]),
            "warn": len([f for f in self.findings if f.severity == "warn"]),
            "info": len([f for f in self.findings if f.severity == "info"]),
        }

class SecurityAuditor:
    """安全审计器"""
    
    def __init__(self, config_path: str, state_dir: str):
        self.config_path = Path(config_path)
        self.state_dir = Path(state_dir)
    
    def run_audit(self) -> AuditReport:
        """执行完整审计"""
        import time
        findings = []
        
        findings.extend(self._check_file_permissions())
        findings.extend(self._check_network_exposure())
        findings.extend(self._check_channel_security())
        
        return AuditReport(
            timestamp=time.time(),
            findings=findings
        )
    
    def _check_file_permissions(self) -> List[AuditFinding]:
        """检查文件权限"""
        findings = []
        
        # 检查配置文件权限
        if self.config_path.exists():
            mode = self.config_path.stat().st_mode
            if mode & stat.S_IROTH:  # 他人可读
                findings.append(AuditFinding(
                    check_id="fs.config.world_readable",
                    severity="critical",
                    title="配置文件他人可读",
                    detail=f"{self.config_path} 权限过于宽松",
                    remediation="chmod 600 " + str(self.config_path)
                ))
        
        return findings
    
    def _check_network_exposure(self) -> List[AuditFinding]:
        """检查网络暴露"""
        # TODO: 检查 Gateway 配置
        return []
    
    def _check_channel_security(self) -> List[AuditFinding]:
        """检查渠道安全"""
        # TODO: 检查 DM/群组访问策略
        return []
```

### 1.4 使用方式

```python
# 命令行
# python -m agent_zero.security audit

# 代码调用
auditor = SecurityAuditor(
    config_path="/a0/conf/settings.yaml",
    state_dir="/a0/memory"
)
report = auditor.run_audit()

print(f"发现 {report.summary['critical']} 个严重问题")
for finding in report.findings:
    print(f"[{finding.severity}] {finding.title}")
```

---

## 2. 配置验证 (Config Validation)

### 2.1 功能描述

使用 Schema 验证配置文件的类型和语义正确性，提前发现配置错误。

### 2.2 验证类型

| 类型 | 示例 |
|------|------|
| **格式验证** | 字段类型错误、缺少必填项 |
| **枚举验证** | 无效的模型名称、未知的渠道 ID |
| **关系验证** | 重复的 Agent ID、循环依赖 |
| **遗留配置** | 旧版配置格式自动迁移 |

### 2.3 实现参考

```python
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
import json

@dataclass
class ValidationIssue:
    """验证问题"""
    path: str       # 如 "chat_model" 或 "mcp_servers.0.url"
    message: str

@dataclass
class ValidationResult:
    """验证结果"""
    ok: bool
    config: Optional[Dict] = None
    issues: List[ValidationIssue] = None

class ConfigValidator:
    """配置验证器"""
    
    # 简化的 Schema 定义
    SCHEMA = {
        "chat_model": {"type": "string", "required": True},
        "utility_model": {"type": "string", "required": False},
        "embedding_model": {"type": "string", "required": False},
        "mcp_servers": {"type": "array", "items": {
            "name": {"type": "string", "required": True},
            "type": {"type": "string", "enum": ["stdio", "sse"]},
        }},
        # ... 更多字段
    }
    
    def validate(self, config: Dict) -> ValidationResult:
        """验证配置"""
        issues = []
        
        # 1. 格式验证
        issues.extend(self._validate_schema(config, self.SCHEMA))
        
        # 2. 语义验证
        issues.extend(self._validate_semantics(config))
        
        if issues:
            return ValidationResult(ok=False, issues=issues)
        
        return ValidationResult(ok=True, config=config)
    
    def _validate_schema(self, data: Dict, schema: Dict, path: str = "") -> List[ValidationIssue]:
        """验证 Schema"""
        issues = []
        
        for key, spec in schema.items():
            full_path = f"{path}.{key}" if path else key
            value = data.get(key)
            
            # 必填检查
            if spec.get("required") and value is None:
                issues.append(ValidationIssue(
                    path=full_path,
                    message=f"必填字段缺失"
                ))
                continue
            
            if value is None:
                continue
            
            # 类型检查
            expected_type = spec.get("type")
            if expected_type == "string" and not isinstance(value, str):
                issues.append(ValidationIssue(
                    path=full_path,
                    message=f"期望 string，实际 {type(value).__name__}"
                ))
            
            # 枚举检查
            if "enum" in spec and value not in spec["enum"]:
                issues.append(ValidationIssue(
                    path=full_path,
                    message=f"无效值 '{value}'，允许值: {spec['enum']}"
                ))
        
        return issues
    
    def _validate_semantics(self, config: Dict) -> List[ValidationIssue]:
        """语义验证"""
        issues = []
        
        # 检查模型格式
        chat_model = config.get("chat_model", "")
        if chat_model and "/" not in chat_model:
            issues.append(ValidationIssue(
                path="chat_model",
                message="模型格式应为 provider/model，如 openai/gpt-4.1"
            ))
        
        return issues
```

### 2.4 使用方式

```python
# 启动时自动验证
validator = ConfigValidator()
result = validator.validate(load_config())

if not result.ok:
    print("配置验证失败:")
    for issue in result.issues:
        print(f"  {issue.path}: {issue.message}")
    sys.exit(1)
```

---

## 3. Gateway API

### 3.1 功能描述

本地 HTTP/WebSocket 服务器，提供统一的 API 网关，支持远程调用和第三方集成。

### 3.2 功能列表

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI 兼容 Chat API |
| `/v1/models` | GET | 列出可用模型 |
| `/health` | GET | 健康检查 |
| `/ws` | WebSocket | 实时事件推送 |

### 3.3 实现参考

```python
from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel
from typing import List, Optional
import asyncio

app = FastAPI(title="Agent Zero Gateway")

# --- OpenAI 兼容 API ---

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: bool = False

class ChatResponse(BaseModel):
    id: str
    choices: List[dict]
    usage: dict

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """OpenAI 兼容的 Chat Completions API"""
    # 调用 Agent Zero 处理
    result = await agent.process_message(
        message=request.messages[-1].content,
        model=request.model
    )
    
    return ChatResponse(
        id="chatcmpl-xxx",
        choices=[{
            "index": 0,
            "message": {"role": "assistant", "content": result},
            "finish_reason": "stop"
        }],
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )

# --- 健康检查 ---

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.9.x"}

# --- WebSocket 实时通信 ---

class ConnectionManager:
    def __init__(self):
        self.connections: List[WebSocket] = []
    
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
    
    async def broadcast(self, event: str, data: dict):
        for ws in self.connections:
            await ws.send_json({"event": event, "data": data})

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            # 处理客户端消息
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except:
        manager.connections.remove(ws)
```

### 3.4 认证配置

```yaml
# 配置示例
gateway:
  enabled: true
  bind: loopback      # loopback | lan | 0.0.0.0
  port: 18789
  
  auth:
    mode: token       # token | password | none
    token: "your-secret-token"
  
  endpoints:
    chat_completions: true
    models: true
```

### 3.5 使用场景

- **第三方应用集成**: 其他应用通过 API 调用 Agent Zero
- **远程控制**: 移动端 App 远程操作
- **多节点集群**: 管理多个 Agent 实例

---

## 实施建议

### 优先级排序

1. **配置验证** (最先) - 防止配置错误导致启动失败
2. **安全审计** (中期) - 生产部署前需要
3. **Gateway API** (按需) - 仅在需要远程访问时实现

### 工作量估算

| 功能 | 估算工作量 | 依赖 |
|------|-----------|------|
| 配置验证 | 2 天 | 无 |
| 安全审计 | 2 天 | 无 |
| Gateway API | 4 天 | FastAPI |

---

> **文档维护者**: AI Assistant  
> **最后更新**: 2026-01-30
