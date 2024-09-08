import asyncio
import json
import asyncio
import json
import os
import time
import random
from aiohttp import web, WSMsgType
import aiohttp_jinja2
from aiohttp_session import get_session
import logging
from typing import List, Dict, Optional
import subprocess
from .analytics import ImprovedAnalytics

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class LivestreamServer:
    def __init__(self):
        self.video_list: List[Dict[str, str]] = []
        self.current_video: Optional[Dict[str, str]] = None
        self.start_time: Optional[float] = None
        self.ffmpeg_process: Optional[asyncio.subprocess.Process] = None
        self.websockets: set = set()
        self.chat_history: List[Dict] = []
        self.output_dir: str = 'hls_output'
        self.video_dir: str = 'mp4-files'
        self.analytics = ImprovedAnalytics()
        self.load_video_list()

    def load_video_list(self) -> None:
        """Load the list of available videos."""
        self.video_list = []
        try:
            for file in os.listdir(self.video_dir):
                if file.endswith('.mp4'):
                    full_path = os.path.join(self.video_dir, file)
                    self.video_list.append({'name': file, 'path': full_path})
            logger.info(f"Loaded {len(self.video_list)} videos")
        except Exception as e:
            logger.error(f"Error loading video list: {str(e)}")

    async def start_streaming(self) -> None:
        """Start the streaming process."""
        os.makedirs(self.output_dir, exist_ok=True)

        while True:
            try:
                if not self.video_list:
                    logger.error("No videos found in the video list.")
                    await asyncio.sleep(5)
                    continue

                self.current_video = random.choice(self.video_list)
                self.start_time = time.time()
                self.analytics.increment_play_count(self.current_video['name'])
                logger.info(
                    f"Starting stream for video: {self.current_video['name']}")

                command = self.get_ffmpeg_command()

                self.ffmpeg_process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                logger.info(
                    f"FFmpeg process started with PID: {self.ffmpeg_process.pid}")

                # Wait for HLS files to be generated
                await self.wait_for_hls_files()

                # Monitor FFmpeg process
                await self.monitor_ffmpeg_process()

                # Broadcast the new state to all connected clients
                await self.broadcast_state()

                # Wait before starting the next video
                await asyncio.sleep(1)
            except Exception as e:
                logger.exception(
                    f"An error occurred during streaming: {str(e)}")
                await asyncio.sleep(5)

    def get_ffmpeg_command(self) -> List[str]:
        """Generate the FFmpeg command."""
        return [
            'ffmpeg',
            '-re',
            '-i', self.current_video['path'],
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-tune', 'zerolatency',
            '-c:a', 'aac',
            '-ar', '44100',
            '-b:a', '128k',
            '-ac', '2',
            '-f', 'hls',
            '-hls_time', '4',
            '-hls_list_size', '20',
            '-hls_flags', 'delete_segments+append_list+omit_endlist',
            '-hls_segment_filename', f'{self.output_dir}/segment%03d.ts',
            '-hls_playlist_type', 'event',
            f'{self.output_dir}/playlist.m3u8'
        ]

    async def wait_for_hls_files(self, timeout: int = 30) -> None:
        """Wait for HLS files to be generated."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(f'{self.output_dir}/playlist.m3u8') and \
               any(f.endswith('.ts') for f in os.listdir(self.output_dir)):
                logger.info("HLS files generated successfully")
                return
            await asyncio.sleep(1)
        logger.error("Timeout: HLS files were not generated")

    async def monitor_ffmpeg_process(self) -> None:
        """Monitor the FFmpeg process and log any errors."""
        try:
            stdout, stderr = await self.ffmpeg_process.communicate()
            if self.ffmpeg_process.returncode != 0:
                logger.error(f"FFmpeg error: {stderr.decode()}")
            else:
                logger.info(
                    f"FFmpeg process completed successfully for {self.current_video['name']}")
        except asyncio.CancelledError:
            self.ffmpeg_process.terminate()
            logger.info("FFmpeg process terminated")

    async def broadcast_state(self) -> None:
        """Broadcast the current state to all connected clients."""
        state = self.get_current_state()
        await self.broadcast(json.dumps({'type': 'state_update', 'state': state}))
        logger.debug("Broadcasted state update to all connected clients")

    async def cleanup_old_files(self) -> None:
        """Clean up old HLS segment files."""
        max_age_days = 0.005  # Keep this value low for livestreaming
        now = time.time()
        cutoff_time = now - (max_age_days * 86400)

        for file_name in os.listdir(self.output_dir):
            if file_name.endswith('.ts'):
                file_path = os.path.join(self.output_dir, file_name)
                if os.path.getmtime(file_path) < cutoff_time:
                    os.remove(file_path)
                    # logger.debug(f"Deleted old file: {file_name}")

    async def cleanup_periodically(self) -> None:
        """Periodically clean up old files."""
        while True:
            await self.cleanup_old_files()
            await asyncio.sleep(3600)  # Run every hour

    def get_current_state(self) -> Dict:
        """Get the current state of the livestream."""
        if self.current_video and self.start_time:
            return {
                'current_video': self.current_video['name'],
                'play_count': 1  # Placeholder for analytics
            }
        return {}

    def get_current_state(self) -> Dict:
        """Get the current state of the livestream."""
        if self.current_video and self.start_time:
            return {
                'current_video': self.current_video['name'],
                'play_count': self.analytics.play_counts.get(self.current_video['name'], 0)
            }
        return {}

    async def get_analytics(self, request: web.Request) -> web.Response:
        """Return analytics data."""
        return web.json_response(self.analytics.get_analytics())

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connections."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.websockets.add(ws)
        session = await get_session(request)
        session_id = session.identity

        self.analytics.start_session(session_id)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self.handle_ws_message(msg.data, session_id)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(
                        f'WebSocket connection closed with exception {ws.exception()}')
        finally:
            self.websockets.remove(ws)
            self.analytics.end_session(session_id)
        return ws

    async def handle_ws_message(self, message: str, session_id: str) -> None:
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            if data['type'] == 'chat':
                chat_message = {
                    'type': 'chat',
                    'username': data['username'],
                    'message': data['message'],
                    'timestamp': time.time()
                }
                self.chat_history.append(chat_message)
                if len(self.chat_history) > 100:
                    self.chat_history.pop(0)
                await self.broadcast(json.dumps(chat_message))
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received from session {session_id}")
        except KeyError:
            logger.error(
                f"Malformed message received from session {session_id}")

    async def broadcast(self, message: str) -> None:
        """Broadcast a message to all connected WebSocket clients."""
        for ws in self.websockets:
            try:
                await ws.send_str(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {str(e)}")

    @aiohttp_jinja2.template('index.html')
    async def index(self, request: web.Request) -> Dict:
        """Render the index page."""
        return {}

    async def video_state(self, request: web.Request) -> web.Response:
        """Return the current video state."""
        state = self.get_current_state()
        return web.json_response(state)

    async def hls_playlist(self, request: web.Request) -> web.Response:
        """Serve the HLS playlist."""
        playlist_path = f'{self.output_dir}/playlist.m3u8'
        if os.path.exists(playlist_path):
            return web.FileResponse(playlist_path)
        else:
            logger.error(f"Playlist not found: {playlist_path}")
            return web.Response(status=404, text="Playlist not found")

    async def hls_segment(self, request: web.Request) -> web.Response:
        """Serve HLS segments."""
        segment = request.match_info['segment']
        segment_path = f'{self.output_dir}/{segment}'
        if os.path.exists(segment_path):
            return web.FileResponse(segment_path)
        else:
            logger.error(f"Segment not found: {segment_path}")
            return web.Response(status=404, text="Segment not found")


async def start_background_tasks(app: web.Application) -> None:
    """Start background tasks."""
    app['livestream_server'] = app['livestream_server']
    app['livestream_task'] = asyncio.create_task(
        app['livestream_server'].start_streaming())
    app['cleanup_task'] = asyncio.create_task(
        app['livestream_server'].cleanup_periodically())


async def cleanup_background_tasks(app: web.Application) -> None:
    """Clean up background tasks."""
    app['livestream_task'].cancel()
    await app['livestream_task']
    app['cleanup_task'].cancel()
    await app['cleanup_task']


def check_ffmpeg() -> None:
    """Check if FFmpeg is installed and accessible."""
    try:
        subprocess.run(['ffmpeg', '-version'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("FFmpeg is installed and accessible")
    except subprocess.CalledProcessError:
        logger.error(
            "FFmpeg is not installed or not accessible. Please install FFmpeg and make sure it's in your system PATH.")
        exit(1)


# Run FFmpeg check when the module is imported
check_ffmpeg()
