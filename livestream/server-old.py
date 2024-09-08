from aiohttp_sse import sse_response
import asyncio
import json
import os
import time
import random
import socket
from aiohttp import web, ClientSession
from dnslib.server import DNSServer, DNSHandler, BaseResolver
from dnslib import RR, QTYPE, A

# Class to manage video streaming and state


class LivestreamServer:
    def __init__(self):
        self.video_list = []
        self.current_video = None
        self.start_time = None
        self.play_counts = {}
        self.ffmpeg_process = None
        self.load_video_list()

    def load_video_list(self):
        video_dir = 'mp4-files'
        self.video_list = []
        for file in os.listdir(video_dir):
            if file.endswith('.mp4'):
                full_path = os.path.join(video_dir, file)
                self.video_list.append({'name': file, 'path': full_path})
                if file not in self.play_counts:
                    self.play_counts[file] = 0

    async def start_streaming(self):
        output_dir = 'hls_output'
        os.makedirs(output_dir, exist_ok=True)

        while True:
            self.current_video = random.choice(self.video_list)
            self.start_time = time.time()
            self.play_counts[self.current_video['name']] += 1

            command = [
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
                '-hls_segment_filename', f'{output_dir}/segment%03d.ts',
                '-hls_playlist_type', 'event',
                f'{output_dir}/playlist.m3u8'
            ]

            self.ffmpeg_process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await self.ffmpeg_process.communicate()

            if self.ffmpeg_process.returncode != 0:
                print(f"FFmpeg error: {stderr.decode()}")

            await asyncio.sleep(1)

    async def cleanup_old_files(self):
        output_dir = 'hls_output'
        max_age_days = .05  # Files older than this will be deleted
        now = time.time()
        cutoff_time = now - (max_age_days * 86400)  # Convert days to seconds

        for file_name in os.listdir(output_dir):
            if file_name.endswith('.ts'):
                file_path = os.path.join(output_dir, file_name)
                file_mtime = os.path.getmtime(file_path)
                if file_mtime < cutoff_time:
                    os.remove(file_path)
                    print(f"Deleted old file: {file_name}")

    async def cleanup_periodically(self):
        while True:
            await self.cleanup_old_files()
            await asyncio.sleep(3600)  # Run cleanup every hour

    def get_current_state(self):
        if self.current_video and self.start_time:
            return {
                'current_video': self.current_video['name'],
                'play_count': self.play_counts[self.current_video['name']]
            }
        return None


livestream_server = LivestreamServer()

# DNS Resolver to resolve hoganlivestream to the server's IP


class HoganDNSResolver(BaseResolver):
    def resolve(self, request, handler):
        reply = request.reply()
        qname = str(request.q.qname)

        if "hoganlivestream." in qname:  # Ensure correct domain
            ip = get_ip()  # Use server's IP address
            reply.add_answer(RR(qname, QTYPE.A, rdata=A(ip), ttl=300))
        return reply


def start_dns_server():
    resolver = HoganDNSResolver()
    dns_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=False)
    dns_server.start_thread()
    print("DNS server started on port 53")

# HTTP Handlers


async def index(request):
    content = open(os.path.join(os.path.dirname(
        __file__), "index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def video_state(request):
    state = livestream_server.get_current_state()
    return web.Response(content_type="application/json", text=json.dumps(state))


async def analytics(request):
    return web.Response(content_type="application/json", text=json.dumps(livestream_server.play_counts))


async def hls_playlist(request):
    playlist_path = 'hls_output/playlist.m3u8'
    if os.path.exists(playlist_path):
        with open(playlist_path, 'rb') as f:
            content = f.read()
        return web.Response(body=content, content_type='application/vnd.apple.mpegurl')
    else:
        return web.Response(status=404)


async def hls_segment(request):
    segment = request.match_info['segment']
    segment_path = f'hls_output/{segment}'
    if os.path.exists(segment_path):
        with open(segment_path, 'rb') as f:
            content = f.read()
        return web.Response(body=content, content_type='video/MP2T')
    else:
        return web.Response(status=404)


async def sse(request):
    async with sse_response(request) as resp:
        try:
            while True:
                state = livestream_server.get_current_state()
                if state:
                    try:
                        await resp.send(json.dumps(state))
                    except ConnectionResetError:
                        print("Client disconnected. Stopping SSE.")
                        break
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print("SSE connection cancelled.")
        except Exception as e:
            print(f"Unexpected error in SSE: {str(e)}")
    return resp


# Reverse proxy function to redirect traffic
async def reverse_proxy(request):
    # Use localhost if the target server is on the same machine
    target_url = f"http://localhost:2020{request.path_qs}"

    async with ClientSession() as session:
        async with session.request(request.method, target_url, headers=request.headers, data=await request.read()) as resp:
            # Forward response status and headers
            proxy_response = web.StreamResponse(
                status=resp.status, headers=resp.headers)
            await proxy_response.prepare(request)

            # Stream the content from the proxied response
            async for data in resp.content.iter_any():
                await proxy_response.write(data)

            return proxy_response


async def start_background_tasks(app):
    app['livestream_task'] = asyncio.create_task(
        livestream_server.start_streaming())


async def cleanup_background_tasks(app):
    app['livestream_task'].cancel()
    app['cleanup_task'] = asyncio.create_task(
        livestream_server.cleanup_periodically())
    await app['livestream_task']


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


if __name__ == "__main__":
    app = web.Application()

    # Set up routes
    app.router.add_get("/", index)
    app.router.add_get("/video-state", video_state)
    app.router.add_get("/analytics", analytics)
    app.router.add_get("/hls/playlist.m3u8", hls_playlist)
    app.router.add_get("/hls/{segment}", hls_segment)
    app.router.add_get("/sse", sse)

    # Catch-all route for reverse proxy (wildcard route)
    app.router.add_route("*", "/{path:.*}", reverse_proxy)

    # Set background tasks for livestream
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    hostname = "HoganLiveStream"
    ip = get_ip()
    port = 2020

    print(f"Starting server on http://{ip}:{port}")
    print(f"You can access the stream at http://{hostname}:{port}")
    print("Make sure to add the following line to your hosts file:")
    print(f"{ip} {hostname}")

    web.run_app(app, host="0.0.0.0", port=port)
