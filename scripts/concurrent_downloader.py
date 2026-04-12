import asyncio
import aiohttp
import aiofiles
from typing import List, Tuple, Dict
import logging

logger = logging.getLogger(__name__)

class ConcurrentDownloader:
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def download_file(self, session: aiohttp.ClientSession,
                          url: str, save_path: str) -> bool:
        """Asynchronously download a single file"""
        async with self.semaphore:
            try:
                async with session.get(url) as response:
                    response.raise_for_status()

                    async with aiofiles.open(save_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)

                logger.info(f"Downloaded: {url}")
                return True
            except Exception as e:
                logger.error(f"Failed to download {url}: {e}")
                return False

    async def download_batch(self, downloads: List[Tuple[str, str]]) -> Dict[str, bool]:
        """Download a batch of files"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            results = {}

            for url, save_path in downloads:
                task = self.download_file(session, url, save_path)
                tasks.append((url, task))

            for url, task in tasks:
                results[url] = await task

            return results
