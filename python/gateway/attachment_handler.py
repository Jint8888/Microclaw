"""
Gateway Attachment Handler

File: python/gateway/attachment_handler.py
"""

import os
import asyncio
import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("gateway.attachment")


class AttachmentHandler:
    """Gateway attachment handler (with TTL cleanup)"""

    def __init__(self, upload_folder: str = None, ttl_hours: int = 24):
        """
        Initialize attachment handler

        Args:
            upload_folder: Upload directory, defaults to tmp/uploads
            ttl_hours: File retention time (hours)
        """
        self.ttl_hours = ttl_hours

        # Determine upload folder
        if upload_folder:
            self.upload_folder = upload_folder
        else:
            # Try to get from project helpers
            try:
                from python.helpers import files
                self.upload_folder = files.get_abs_path("tmp/uploads")
            except ImportError:
                self.upload_folder = os.path.join(os.getcwd(), "tmp", "uploads")

        self.internal_path_prefix = "/a0/tmp/uploads"  # Docker internal path

        # Check if running in Docker
        self.is_docker = os.environ.get("DOCKER_CONTAINER") == "1"

        # Ensure directory exists
        os.makedirs(self.upload_folder, exist_ok=True)

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self):
        """Start periodic cleanup task"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(f"Attachment cleanup task started (TTL: {self.ttl_hours}h)")

    async def stop_cleanup_task(self):
        """Stop cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self):
        """Periodically clean expired files"""
        while True:
            try:
                await asyncio.sleep(3600)  # Check every hour
                await self._cleanup_old_files()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def _cleanup_old_files(self):
        """Clean expired files"""
        cutoff = datetime.now() - timedelta(hours=self.ttl_hours)
        cutoff_timestamp = cutoff.timestamp()
        cleaned_count = 0

        try:
            for f in Path(self.upload_folder).iterdir():
                if f.is_file() and f.stat().st_mtime < cutoff_timestamp:
                    f.unlink(missing_ok=True)
                    cleaned_count += 1

            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} expired attachment(s)")
        except Exception as e:
            logger.error(f"Error during file cleanup: {e}")

    async def download_from_url(
        self,
        url: str,
        original_filename: str = None,
        timeout: int = 60
    ) -> str:
        """
        Download attachment from URL and return local path

        Args:
            url: Media file URL
            original_filename: Original filename (to preserve extension)
            timeout: Download timeout (seconds)

        Returns:
            Local file path (for passing to UserMessage.attachments)
        """
        try:
            from werkzeug.utils import secure_filename
        except ImportError:
            def secure_filename(fn):
                return fn.replace("/", "_").replace("\\", "_")

        # Extract extension
        if original_filename:
            ext = os.path.splitext(secure_filename(original_filename))[1]
        else:
            ext = os.path.splitext(url.split('?')[0])[1] or '.bin'

        # Generate unique filename
        unique_filename = f"{uuid4().hex}{ext}"
        local_path = os.path.join(self.upload_folder, unique_filename)

        # Download file
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status == 200:
                        with open(local_path, 'wb') as f:
                            f.write(await resp.read())
                    else:
                        raise Exception(f"Failed to download attachment: HTTP {resp.status}")
        except ImportError:
            # Fallback to httpx if aiohttp not available
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=timeout)
                if resp.status_code == 200:
                    with open(local_path, 'wb') as f:
                        f.write(resp.content)
                else:
                    raise Exception(f"Failed to download attachment: HTTP {resp.status_code}")

        logger.debug(f"Downloaded attachment: {unique_filename}")

        # Return appropriate path
        if self.is_docker:
            return os.path.join(self.internal_path_prefix, unique_filename)
        else:
            return local_path

    async def save_from_bytes(self, data: bytes, filename: str) -> str:
        """
        Save attachment from binary data

        Args:
            data: File binary data
            filename: Original filename

        Returns:
            Local file path
        """
        try:
            from werkzeug.utils import secure_filename
        except ImportError:
            def secure_filename(fn):
                return fn.replace("/", "_").replace("\\", "_")

        safe_name = secure_filename(filename)
        ext = os.path.splitext(safe_name)[1] or '.bin'
        unique_filename = f"{uuid4().hex}{ext}"
        local_path = os.path.join(self.upload_folder, unique_filename)

        with open(local_path, 'wb') as f:
            f.write(data)

        if self.is_docker:
            return os.path.join(self.internal_path_prefix, unique_filename)
        else:
            return local_path

    def cleanup_file(self, file_path: str):
        """
        Immediately clean up specified file

        Args:
            file_path: File path (supports Docker internal path)
        """
        try:
            # Convert to actual local path
            if file_path.startswith(self.internal_path_prefix):
                filename = os.path.basename(file_path)
                actual_path = os.path.join(self.upload_folder, filename)
            else:
                actual_path = file_path

            if os.path.exists(actual_path):
                os.remove(actual_path)
                logger.debug(f"Cleaned up attachment: {actual_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup attachment {file_path}: {e}")

    def get_local_path(self, internal_path: str) -> str:
        """Convert internal path to actual local path"""
        if internal_path.startswith(self.internal_path_prefix):
            filename = os.path.basename(internal_path)
            return os.path.join(self.upload_folder, filename)
        return internal_path
