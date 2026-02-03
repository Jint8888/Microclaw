# Browser-Use Library Migration Guide

## Overview

This document describes the migration from the old Playwright-based browser-use API to the new CDP (Chrome DevTools Protocol) based API. The new version provides a more robust, event-driven architecture for browser automation.

## Background

### Problem

Agent-Zero's `browser_agent.py` was encountering the following error:

```
Error: 'BrowserSession' object has no attribute 'browser_context'
```

### Root Cause

The browser-use library underwent a major architectural change:

| Aspect | Old Version (≤0.11.x) | New Version (CDP-based) |
|--------|----------------------|-------------------------|
| Architecture | Playwright-based | Pure CDP (Chrome DevTools Protocol) |
| Session Management | `browser_context` attribute | Event-driven with `SessionManager` |
| Browser Control | Playwright APIs | CDP commands via `_cdp_*` methods |
| Lifecycle | `close()` method | `stop()` or `kill()` methods |

## Changes Made

### File: `python/tools/browser_agent.py`

#### Change 1: Viewport Configuration (Lines 87-92)

**Before:**
```python
if self.browser_session:
    try:
        page = await self.browser_session.get_current_page()
        if page:
            await page.set_viewport_size({"width": 1024, "height": 2048})
    except Exception as e:
        PrintStyle().warning(f"Could not force set viewport size: {e}")
```

**After:**
```python
if self.browser_session:
    try:
        # New CDP-based API: use _cdp_set_viewport instead of page.set_viewport_size
        await self.browser_session._cdp_set_viewport(width=1024, height=2048)
    except Exception as e:
        PrintStyle().warning(f"Could not force set viewport size: {e}")
```

**Reason:** The new API provides a direct CDP method for viewport configuration instead of going through the Playwright page object.

---

#### Change 2: Init Script Injection (Lines 96-105)

**Before:**
```python
if self.browser_session and self.browser_session.browser_context:
    js_override = files.get_abs_path("lib/browser/init_override.js")
    await self.browser_session.browser_context.add_init_script(path=js_override)
```

**After:**
```python
if self.browser_session:
    try:
        js_override = files.get_abs_path("lib/browser/init_override.js")
        with open(js_override, 'r', encoding='utf-8') as f:
            script_content = f.read()
        await self.browser_session._cdp_add_init_script(script_content)
    except Exception as e:
        PrintStyle().warning(f"Could not add init script: {e}")
```

**Reason:**
- The `browser_context` attribute no longer exists in the new API
- The new `_cdp_add_init_script()` method accepts script content as a string, not a file path
- Added proper error handling for robustness

---

#### Change 3: Session Cleanup (Lines 129-130)

**Before:**
```python
loop.run_until_complete(self.browser_session.close())
```

**After:**
```python
# New browser-use API: use stop() instead of close()
loop.run_until_complete(self.browser_session.stop())
```

**Reason:** The new API uses `stop()` for graceful shutdown (keeps browser alive if `keep_alive=True`) or `kill()` for forceful termination.

## New API Reference

### Key Methods in New BrowserSession

| Method | Description |
|--------|-------------|
| `start()` | Start the browser session |
| `stop()` | Stop gracefully (respects `keep_alive` setting) |
| `kill()` | Force stop (always terminates browser) |
| `_cdp_set_viewport(width, height)` | Set viewport size via CDP |
| `_cdp_add_init_script(script)` | Add JavaScript to run on new documents |
| `_cdp_navigate(url)` | Navigate to URL via CDP |
| `get_current_page()` | Get current page (still compatible) |
| `get_browser_state_summary()` | Get browser state (renamed from `get_state_summary`) |

### Event-Driven Architecture

The new browser-use uses an event bus pattern:

```python
# Example: Navigate to URL
await browser_session.event_bus.dispatch(NavigateToUrlEvent(url="https://example.com"))

# Example: Switch tabs
await browser_session.event_bus.dispatch(SwitchTabEvent(target_id=target_id))
```

### Watchdog System

The new version includes specialized watchdogs for different concerns:

- `LocalBrowserWatchdog` - Local browser lifecycle
- `SecurityWatchdog` - Domain restrictions and security
- `DownloadsWatchdog` - File download handling
- `DOMWatchdog` - DOM tree management
- `ScreenshotWatchdog` - Screenshot capture
- And more...

## Compatibility Notes

### Still Compatible

These APIs remain compatible with the new version:

- `BrowserSession()` constructor
- `BrowserProfile()` configuration
- `browser_session.start()`
- `browser_session.get_current_page()`
- `browser_use.Agent()` for browser automation
- `browser_use.Controller()` for action registration

### Breaking Changes

| Old API | New API | Notes |
|---------|---------|-------|
| `browser_session.browser_context` | Removed | Use CDP methods instead |
| `browser_session.close()` | `browser_session.stop()` | Or `kill()` for force close |
| `page.set_viewport_size()` | `_cdp_set_viewport()` | Direct CDP call |
| `browser_context.add_init_script(path=...)` | `_cdp_add_init_script(content)` | Takes string content |
| `get_state_summary()` | `get_browser_state_summary()` | Method renamed |

## Testing

After applying these changes, test the browser agent with:

```
User message: 使用browser_agent工具帮我从unsplash网站下载1张狮子的图片返回。
```

Expected behavior:
1. Browser launches in headless mode
2. Navigates to unsplash.com
3. Searches for "lion"
4. Downloads the first image
5. Returns success message

## Troubleshooting

### Error: "CDP client not initialized"

The browser session hasn't started yet. Ensure `await browser_session.start()` is called before any operations.

### Error: "No valid agent focus available"

The target tab may have closed. The SessionManager will attempt recovery, but you may need to create a new tab.

### Error: "Target has detached"

The page/iframe has been closed or navigated away. Handle this gracefully and retry with a valid target.

## References

- Browser-Use GitHub: https://github.com/browser-use/browser-use
- CDP Documentation: https://chromedevtools.github.io/devtools-protocol/

---

*Document created: 2025-01-31*
*Last updated: 2025-01-31*
