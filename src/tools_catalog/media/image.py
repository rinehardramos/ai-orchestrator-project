"""
Image tool — generate images using Google Imagen.

Wraps generate_image from src/execution/worker/tools.py.
"""
from __future__ import annotations

from src.plugins.base import Tool, ToolContext
from src.execution.worker.tools import generate_image as _generate_image


class ImageTool(Tool):
    type = "media"
    name = "image"
    description = "Generate images using Google Imagen AI models"
    node = "worker"

    def get_tool_schemas(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "generate_image",
                    "description": (
                        "Generate an image from a text prompt using Google Imagen. "
                        "Saves the image to the workspace and returns the filename. "
                        "Requires GOOGLE_API_KEY environment variable."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "Detailed description of the image to generate",
                            },
                            "filename": {
                                "type": "string",
                                "description": (
                                    "Output filename (e.g. 'duck.png'). "
                                    "Defaults to a name derived from the prompt."
                                ),
                                "default": "",
                            },
                        },
                        "required": ["prompt"],
                    },
                },
            }
        ]

    async def call_tool(self, tool_name: str, args: dict, ctx: ToolContext):
        if tool_name == "generate_image":
            return _generate_image(ctx.workspace_dir, **args)
        return f"ERROR: Unknown tool '{tool_name}'"


tool_class = ImageTool
