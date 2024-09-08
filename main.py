import asyncio
from aiohttp import web
import aiohttp_jinja2
import jinja2
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import base64
from cryptography import fernet
import os

from livestream.server import LivestreamServer, start_background_tasks, cleanup_background_tasks
from livestream.dns_resolver import start_dns_server
from livestream.auth import setup_auth, init_db
from livestream.admin import setup_admin_routes


def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


async def index(request):
    return aiohttp_jinja2.render_template('index.html', request, {})


async def init_app():
    app = web.Application()

    # Setup encrypted session
    fernet_key = fernet.Fernet.generate_key()
    secret_key = base64.urlsafe_b64decode(fernet_key)
    setup_session(app, EncryptedCookieStorage(secret_key))

    # Initialize database
    await init_db(app)

    # Setup Jinja2 templates
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(template_dir))

    # Initialize LivestreamServer
    livestream_server = LivestreamServer()

    # Setup routes
    app.router.add_get("/", index)
    app.router.add_get("/video-state", livestream_server.video_state)
    app.router.add_get("/analytics", livestream_server.get_analytics)
    app.router.add_get("/hls/playlist.m3u8", livestream_server.hls_playlist)
    app.router.add_get("/hls/{segment}", livestream_server.hls_segment)
    app.router.add_get("/ws", livestream_server.handle_websocket)

    # Setup authentication
    setup_auth(app)

    # Setup admin routes
    setup_admin_routes(app, livestream_server)

    # Setup background tasks
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    return app


def main():
    # Start DNS server
    start_dns_server()

    # Run the server
    hostname = "HoganLiveStream"
    ip = get_ip()
    port = 2020

    print(f"Starting server on http://{ip}:{port}")
    print(f"You can access the stream at http://{hostname}:{port}")
    print("Make sure to add the following line to your hosts file:")
    print(f"{ip} {hostname}")

    web.run_app(init_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
