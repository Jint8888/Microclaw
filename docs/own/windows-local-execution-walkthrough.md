# Windows Local Execution Walkthrough

This document describes the changes made to Agent Zero to support Windows local development without requiring Docker containers or SSH connections.

## Overview

By default, Agent Zero was designed to run inside a Docker container (Kali Linux) and use SSH for code execution when running in development mode. These modifications enable Agent Zero to run natively on Windows using PowerShell and local Python TTY.

## Changes Summary

### 1. Default Settings Changed (`python/helpers/settings.py`)

#### Shell Interface Default
```python
# Before
shell_interface="local" if runtime.is_dockerized() else "ssh",

# After
shell_interface="local",
```
**Effect**: Always use local Python TTY by default instead of SSH.

#### RFC URL Default
```python
# Before
rfc_url="localhost",

# After
rfc_url="",
```
**Effect**: Disable RFC (Remote Function Call) by default to prevent connection errors.

### 2. RFC Configuration Check (`python/helpers/runtime.py`)

#### Added `is_rfc_configured()` function
```python
def is_rfc_configured() -> bool:
    """Check if RFC is properly configured (rfc_url is not empty)"""
    set = settings.get_settings()
    return bool(set.get("rfc_url", "").strip())
```
**Effect**: Provides a way to check if RFC is properly configured before attempting remote calls.

#### Modified `call_development_function()`
```python
# Before
if is_development():
    # Always try RFC call...

# After
if is_development() and is_rfc_configured():
    # Only try RFC call if configured...
else:
    # Execute locally
```
**Effect**: When RFC is not configured, functions execute locally instead of failing with connection errors.

### 3. Job Loop RFC Check (`python/helpers/job_loop.py`)

```python
# Before
if runtime.is_development():
    await runtime.call_development_function(pause_loop)

# After
if runtime.is_development() and runtime.is_rfc_configured():
    await runtime.call_development_function(pause_loop)
```
**Effect**: Prevents RFC connection errors when running without Docker.

### 4. Environment Prompts (`prompts/agent.system.main.environment.md`)

```markdown
# Before
## Environment
live in kali linux docker container use debian kali packages
agent zero framework is python project in /a0 folder
linux fully root accessible via terminal

# After
## Environment
live in Windows development environment using PowerShell as default shell
agent zero framework is python project in current working directory
use PowerShell commands for terminal operations (Get-ChildItem, Set-Location, etc.)
use winget, choco, or pip/npm for package installation
for cross-platform compatibility, prefer Python scripts over shell commands when possible
```

### 5. Code Execution Tool Prompts (`prompts/agent.system.tool.code_exe.md`)

- Changed package manager reference from `apt-get` to `winget`/`choco`
- Added note about using PowerShell commands on Windows
- Updated terminal command example to use PowerShell syntax

## File Changes List

| File | Change Type | Description |
|------|-------------|-------------|
| `python/helpers/settings.py:1515` | Modified | RFC URL default: `"localhost"` → `""` |
| `python/helpers/settings.py:1519` | Modified | Shell interface default: conditional → `"local"` |
| `python/helpers/runtime.py:64-67` | Added | New `is_rfc_configured()` function |
| `python/helpers/runtime.py:105` | Modified | Added RFC check to `call_development_function()` |
| `python/helpers/job_loop.py:20` | Modified | Added RFC check before pause call |
| `prompts/agent.system.main.environment.md` | Rewritten | Windows environment description |
| `prompts/agent.system.tool.code_exe.md` | Modified | PowerShell commands and examples |

## Usage

### Starting Agent Zero on Windows

```powershell
cd H:\AI\agent-zero
.\start.ps1
```

### Verifying Local Execution Mode

1. Open http://localhost:5000
2. Go to Settings → Developer tab
3. Verify:
   - **Shell Interface**: `Local Python TTY`
   - **RFC Destination URL**: (empty)

### If You Need to Re-enable SSH/Docker Mode

1. Go to Settings → Developer tab
2. Set **Shell Interface** to `SSH`
3. Set **RFC Destination URL** to `localhost`
4. Configure SSH port (default: 55022)
5. Start Docker container with matching ports

## Troubleshooting

### Error: "Cannot connect to port 55022"
**Cause**: Shell Interface is set to SSH but no Docker container is running.
**Solution**: Change Shell Interface to `Local Python TTY` in Settings.

### Error: "InvalidUrlClientError: http://:55080/rfc"
**Cause**: RFC URL is empty but code tried to make RFC call.
**Solution**: This should be fixed by the `is_rfc_configured()` check. If still occurring, check for code that bypasses this check.

### PowerShell commands not working
**Cause**: Agent may still use Linux commands from its training.
**Solution**: Prompts have been updated, but you may need to explicitly ask for PowerShell commands.

## Architecture Notes

### Shell Execution Flow

```
code_execution_tool.py
    ├── SSH Mode (shell_interface="ssh")
    │   └── SSHInteractiveSession (shell_ssh.py)
    │       └── Connects to Docker via SSH
    │
    └── Local Mode (shell_interface="local")  ← DEFAULT NOW
        └── LocalInteractiveSession (shell_local.py)
            └── tty_session.py
                └── PowerShell.exe (on Windows)
                └── /bin/bash (on Linux/Mac)
```

### RFC Execution Flow

```
call_development_function()
    ├── is_rfc_configured() = True
    │   └── Remote call via HTTP to Docker container
    │
    └── is_rfc_configured() = False  ← DEFAULT NOW
        └── Execute function locally
```

## Version Information

- **Modified Date**: 2026-01-31
- **Agent Zero Version**: Based on latest main branch
- **Target Platform**: Windows 10/11 with PowerShell
