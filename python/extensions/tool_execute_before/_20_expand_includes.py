import re
import os
from typing import Any
from python.helpers.extension import Extension
from python.helpers import files

class ExpandIncludes(Extension):
    async def execute(self, tool_args: dict[str, Any] | None = None, tool_name: str = "", **kwargs):
        if not tool_args:
            return

        def replace_placeholders(value: Any) -> Any:
            if isinstance(value, str):
                # Regex for §§include(path) - handling nested parentheses simply by taking non-parentheses
                return re.sub(r"§§include\(([^)]+)\)", self._replacer, value)
            if isinstance(value, dict):
                return {k: replace_placeholders(v) for k, v in value.items()}
            if isinstance(value, list):
                return [replace_placeholders(v) for v in value]
            if isinstance(value, tuple):
                return tuple(replace_placeholders(v) for v in value)
            return value

        updated_args = replace_placeholders(tool_args)
        tool_args.clear()
        tool_args.update(updated_args)

    def _replacer(self, match):
        path = match.group(1)
        try:
            # Fix path for dev environment if needed
            path = files.fix_dev_path(path)
            
            # Check extension for binary/image
            ext = os.path.splitext(path)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico']:
                # Read as base64
                return files.read_file_base64(path)
            else:
                # Read as text
                return files.read_file(path)
        except Exception:
            # On error (file not found etc), return the original match so it fails visibly later or is handled otherwise
            return match.group(0)
