import asyncio
import base64
import json
import os
import tempfile
from typing import Any, Dict, List, Optional
from src.plugins.base import Tool, ToolContext

try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class WebAutomationTool(Tool):
    type = "web"
    name = "web"
    description = "Automate web browsers for navigation, form filling, clicking, and data extraction"
    node = "worker"
    
    _method_map = {
        "web_navigate": "_navigate",
        "web_click": "_click",
        "web_fill": "_fill",
        "web_select": "_select",
        "web_check": "_check",
        "web_uncheck": "_uncheck",
        "web_wait": "_wait",
        "web_screenshot": "_screenshot",
        "web_get_text": "_get_text",
        "web_get_attribute": "_get_attribute",
        "web_evaluate": "_evaluate",
        "web_press": "_press",
        "web_hover": "_hover",
        "web_scroll": "_scroll",
        "web_upload": "_upload",
        "web_download": "_download",
        "web_new_page": "_new_page",
        "web_close_page": "_close_page",
        "web_list_pages": "_list_pages",
        "web_switch_page": "_switch_page",
        "web_close": "_close_browser",
    }

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._pages: Dict[str, Page] = {}
        self._current_page: str = "default"
        self._playwright = None

    def initialize(self, config: dict) -> None:
        self.config = config
        self.headless = config.get("headless", True)
        self.timeout = config.get("timeout", 30000)
        self.slow_mo = config.get("slow_mo", 0)
        self.browser_type = config.get("browser", "chromium")
        self.user_data_dir = config.get("user_data_dir")
        self.viewport = config.get("viewport", {"width": 1280, "height": 720})
        self.user_agent = config.get("user_agent")
        self.locale = config.get("locale", "en-US")
        self.timezone = config.get("timezone", "Asia/Manila")

    def get_tool_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_navigate",
                    "description": "Navigate to a URL. Opens browser if not already open.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The URL to navigate to"},
                            "wait_until": {
                                "type": "string",
                                "enum": ["load", "domcontentloaded", "networkidle"],
                                "description": "Wait condition (default: load)"
                            }
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_click",
                    "description": "Click on an element",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector or text to click"},
                            "by_text": {"type": "boolean", "description": "Click by visible text instead of CSS selector"},
                            "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button (default: left)"},
                            "double": {"type": "boolean", "description": "Double-click"}
                        },
                        "required": ["selector"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fill",
                    "description": "Fill a text input or textarea",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector for the input field"},
                            "value": {"type": "string", "description": "Value to fill"},
                            "clear": {"type": "boolean", "description": "Clear field before filling (default: true)"},
                            "press_enter": {"type": "boolean", "description": "Press Enter after filling"}
                        },
                        "required": ["selector", "value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_select",
                    "description": "Select an option from a dropdown",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector for the select element"},
                            "value": {"type": "string", "description": "Value or label to select"}
                        },
                        "required": ["selector", "value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_check",
                    "description": "Check a checkbox or radio button",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector for the checkbox/radio"}
                        },
                        "required": ["selector"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_uncheck",
                    "description": "Uncheck a checkbox",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector for the checkbox"}
                        },
                        "required": ["selector"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_wait",
                    "description": "Wait for an element or a duration",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector to wait for"},
                            "timeout": {"type": "integer", "description": "Timeout in ms (default: 30000)"},
                            "state": {
                                "type": "string",
                                "enum": ["visible", "hidden", "attached", "detached"],
                                "description": "State to wait for (default: visible)"
                            },
                            "seconds": {"type": "integer", "description": "Wait for N seconds instead of selector"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_screenshot",
                    "description": "Take a screenshot",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "full_page": {"type": "boolean", "description": "Capture full scrollable page (default: false)"},
                            "selector": {"type": "string", "description": "CSS selector to screenshot specific element"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_get_text",
                    "description": "Get text content from page or element",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector (optional, gets all text if not provided)"},
                            "all": {"type": "boolean", "description": "Return all matching elements as list"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_get_attribute",
                    "description": "Get an attribute value from an element",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector"},
                            "attribute": {"type": "string", "description": "Attribute name (e.g., href, src, value)"}
                        },
                        "required": ["selector", "attribute"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_evaluate",
                    "description": "Execute JavaScript in the browser",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "script": {"type": "string", "description": "JavaScript code to execute"}
                        },
                        "required": ["script"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_press",
                    "description": "Press keyboard keys",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Key to press (e.g., Enter, Tab, Escape, ArrowDown)"},
                            "selector": {"type": "string", "description": "CSS selector to focus before pressing (optional)"}
                        },
                        "required": ["key"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_hover",
                    "description": "Hover over an element",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector to hover over"}
                        },
                        "required": ["selector"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_scroll",
                    "description": "Scroll the page",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "direction": {"type": "string", "enum": ["up", "down", "top", "bottom"], "description": "Scroll direction"},
                            "amount": {"type": "integer", "description": "Pixels to scroll (for up/down)"}
                        },
                        "required": ["direction"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_upload",
                    "description": "Upload a file to a file input",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector for file input"},
                            "file_path": {"type": "string", "description": "Path to the file to upload"}
                        },
                        "required": ["selector", "file_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_download",
                    "description": "Download a file from a link",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string", "description": "CSS selector for download link/button"},
                            "timeout": {"type": "integer", "description": "Download timeout in ms (default: 60000)"}
                        },
                        "required": ["selector"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_new_page",
                    "description": "Open a new browser page/tab",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Name for the new page (default: auto-generated)"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_close_page",
                    "description": "Close the current or a specific page",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Page name to close (default: current)"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_list_pages",
                    "description": "List all open browser pages",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_switch_page",
                    "description": "Switch to a different browser page",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Name of the page to switch to"}
                        },
                        "required": ["name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_close",
                    "description": "Close the browser and release resources",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext) -> Any:
        if not PLAYWRIGHT_AVAILABLE:
            return "Error: Playwright is not installed. Run: pip install playwright && playwright install chromium"
        
        method = self._method_map.get(tool_name)
        if not method:
            return f"Unknown function: {tool_name}"
        
        handler = getattr(self, method, None)
        if not handler:
            return f"Method not implemented: {tool_name}"
        
        try:
            return await handler(args, ctx)
        except Exception as e:
            return f"Error: {str(e)}"

    async def _ensure_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            
            browser_launcher = getattr(self._playwright, self.browser_type)
            
            launch_args = {
                "headless": self.headless,
                "timeout": self.timeout,
            }
            if self.slow_mo:
                launch_args["slow_mo"] = self.slow_mo
            
            self._browser = await browser_launcher.launch(**launch_args)
            
            context_args = {
                "viewport": self.viewport,
                "locale": self.locale,
                "timezone_id": self.timezone,
            }
            if self.user_agent:
                context_args["user_agent"] = self.user_agent
            if self.user_data_dir:
                context_args["user_data_dir"] = self.user_data_dir
            
            self._context = await self._browser.new_context(**context_args)
            
            page = await self._context.new_page()
            page.set_default_timeout(self.timeout)
            self._pages["default"] = page
            self._current_page = "default"

    def _get_current_page(self) -> Page:
        if not self._pages:
            raise ValueError("No pages open. Call web_navigate first.")
        return self._pages.get(self._current_page)

    async def _navigate(self, args: dict, ctx: ToolContext) -> Any:
        url = args.get("url")
        wait_until = args.get("wait_until", "load")
        
        await self._ensure_browser()
        page = self._get_current_page()
        
        await page.goto(url, wait_until=wait_until, timeout=self.timeout)
        
        return {
            "status": "navigated",
            "url": page.url,
            "title": await page.title()
        }

    async def _click(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        by_text = args.get("by_text", False)
        button = args.get("button", "left")
        double = args.get("double", False)
        
        page = self._get_current_page()
        
        if by_text:
            selector = f"text={selector}"
        
        click_args = {"button": button}
        if double:
            await page.dblclick(selector, **click_args)
        else:
            await page.click(selector, **click_args)
        
        return {"status": "clicked", "selector": selector}

    async def _fill(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        value = args.get("value")
        clear = args.get("clear", True)
        press_enter = args.get("press_enter", False)
        
        page = self._get_current_page()
        
        if clear:
            await page.fill(selector, value)
        else:
            await page.type(selector, value)
        
        if press_enter:
            await page.press(selector, "Enter")
        
        return {"status": "filled", "selector": selector, "value": value}

    async def _select(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        value = args.get("value")
        
        page = self._get_current_page()
        await page.select_option(selector, label=value)
        
        return {"status": "selected", "selector": selector, "value": value}

    async def _check(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        page = self._get_current_page()
        await page.check(selector)
        return {"status": "checked", "selector": selector}

    async def _uncheck(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        page = self._get_current_page()
        await page.uncheck(selector)
        return {"status": "unchecked", "selector": selector}

    async def _wait(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        timeout = args.get("timeout", self.timeout)
        state = args.get("state", "visible")
        seconds = args.get("seconds")
        
        page = self._get_current_page()
        
        if seconds:
            await asyncio.sleep(seconds)
            return {"status": "waited", "seconds": seconds}
        
        if selector:
            await page.wait_for_selector(selector, state=state, timeout=timeout)
            return {"status": "waited", "selector": selector, "state": state}
        
        return {"status": "waited", "message": "No selector or seconds provided"}

    async def _screenshot(self, args: dict, ctx: ToolContext) -> Any:
        full_page = args.get("full_page", False)
        selector = args.get("selector")
        
        page = self._get_current_page()
        
        tmp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()
        
        if selector:
            element = await page.query_selector(selector)
            await element.screenshot(path=tmp_path)
        else:
            await page.screenshot(path=tmp_path, full_page=full_page)
        
        with open(tmp_path, "rb") as f:
            screenshot_bytes = f.read()
        
        os.unlink(tmp_path)
        
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        
        return {
            "status": "screenshot",
            "base64": screenshot_b64,
            "size_bytes": len(screenshot_bytes),
            "full_page": full_page
        }

    async def _get_text(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        all_matches = args.get("all", False)
        
        page = self._get_current_page()
        
        if not selector:
            text = await page.text_content("body")
            return {"text": text}
        
        if all_matches:
            elements = await page.query_selector_all(selector)
            texts = []
            for el in elements:
                text = await el.text_content()
                texts.append(text)
            return {"texts": texts, "count": len(texts)}
        
        text = await page.text_content(selector)
        return {"text": text}

    async def _get_attribute(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        attribute = args.get("attribute")
        
        page = self._get_current_page()
        value = await page.get_attribute(selector, attribute)
        
        return {"attribute": attribute, "value": value}

    async def _evaluate(self, args: dict, ctx: ToolContext) -> Any:
        script = args.get("script")
        page = self._get_current_page()
        result = await page.evaluate(script)
        return {"result": result}

    async def _press(self, args: dict, ctx: ToolContext) -> Any:
        key = args.get("key")
        selector = args.get("selector")
        
        page = self._get_current_page()
        
        if selector:
            await page.press(selector, key)
        else:
            await page.keyboard.press(key)
        
        return {"status": "pressed", "key": key}

    async def _hover(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        page = self._get_current_page()
        await page.hover(selector)
        return {"status": "hovered", "selector": selector}

    async def _scroll(self, args: dict, ctx: ToolContext) -> Any:
        direction = args.get("direction")
        amount = args.get("amount", 300)
        
        page = self._get_current_page()
        
        if direction == "top":
            await page.evaluate("window.scrollTo(0, 0)")
        elif direction == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "down":
            await page.evaluate(f"window.scrollBy(0, {amount})")
        
        return {"status": "scrolled", "direction": direction}

    async def _upload(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        file_path = args.get("file_path")
        
        page = self._get_current_page()
        
        if not os.path.exists(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}
        
        await page.set_input_files(selector, file_path)
        return {"status": "uploaded", "file": file_path}

    async def _download(self, args: dict, ctx: ToolContext) -> Any:
        selector = args.get("selector")
        timeout = args.get("timeout", 60000)
        
        page = self._get_current_page()
        
        async with page.expect_download(timeout=timeout) as download_info:
            await page.click(selector)
        
        download = await download_info.value
        
        tmp_file = tempfile.NamedTemporaryFile(suffix=os.path.splitext(download.suggested_filename)[1], delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()
        
        await download.save_as(tmp_path)
        
        return {
            "status": "downloaded",
            "filename": download.suggested_filename,
            "path": tmp_path,
            "size_bytes": os.path.getsize(tmp_path)
        }

    async def _new_page(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name", f"page_{len(self._pages) + 1}")
        
        await self._ensure_browser()
        page = await self._context.new_page()
        page.set_default_timeout(self.timeout)
        
        self._pages[name] = page
        self._current_page = name
        
        return {"status": "created", "name": name, "total_pages": len(self._pages)}

    async def _close_page(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name", self._current_page)
        
        if name not in self._pages:
            return {"status": "error", "message": f"Page '{name}' not found"}
        
        await self._pages[name].close()
        del self._pages[name]
        
        if name == self._current_page and self._pages:
            self._current_page = list(self._pages.keys())[0]
        
        return {"status": "closed", "name": name, "remaining_pages": len(self._pages)}

    async def _list_pages(self, args: dict, ctx: ToolContext) -> Any:
        pages_info = []
        for name, page in self._pages.items():
            pages_info.append({
                "name": name,
                "url": page.url,
                "current": name == self._current_page
            })
        
        return {"pages": pages_info, "current": self._current_page}

    async def _switch_page(self, args: dict, ctx: ToolContext) -> Any:
        name = args.get("name")
        
        if name not in self._pages:
            return {"status": "error", "message": f"Page '{name}' not found"}
        
        self._current_page = name
        
        return {"status": "switched", "current": name, "url": self._pages[name].url}

    async def _close_browser(self, args: dict, ctx: ToolContext) -> Any:
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._pages = {}
            self._current_page = "default"
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        
        return {"status": "closed"}


tool_class = WebAutomationTool
