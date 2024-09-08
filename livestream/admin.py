from aiohttp import web
import aiohttp_jinja2
from aiohttp_session import get_session
import os


@aiohttp_jinja2.template('admin-panel.html')
async def admin_panel(request):
    session = await get_session(request)
    if 'user_id' not in session or not session.get('is_admin'):
        raise web.HTTPForbidden(text='Unauthorized')

    livestream_server = request.app['livestream_server']
    return {
        'video_list': livestream_server.video_list,
        'analytics': livestream_server.analytics.get_analytics(),
        'current_video': livestream_server.current_video
    }


async def add_video(request):
    session = await get_session(request)
    if 'user_id' not in session or not session.get('is_admin'):
        return web.Response(text='Unauthorized', status=401)

    livestream_server = request.app['livestream_server']
    reader = await request.multipart()
    field = await reader.next()
    if field.name == 'video':
        filename = field.filename
        size = 0
        with open(os.path.join('mp4-files', filename), 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
        livestream_server.load_video_list()
        return web.Response(text=f"Uploaded {filename} ({size} bytes)")
    return web.Response(text="No video file received", status=400)


async def remove_video(request):
    session = await get_session(request)
    if 'user' not in session:
        return web.Response(text='Unauthorized', status=401)

    livestream_server = request.app['livestream_server']
    data = await request.post()
    filename = data['filename']
    try:
        os.remove(os.path.join('mp4-files', filename))
        livestream_server.load_video_list()
        return web.Response(text=f"Removed {filename}")
    except FileNotFoundError:
        return web.Response(text=f"File {filename} not found", status=404)


def setup_admin_routes(app, livestream_server):
    app['livestream_server'] = livestream_server
    app.router.add_get("/admin", admin_panel)
    app.router.add_post("/admin/add_video", add_video)
    app.router.add_post("/admin/remove_video", remove_video)
