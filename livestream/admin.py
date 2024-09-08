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
        try:
            os.makedirs('mp4-files', exist_ok=True)
            with open(os.path.join('mp4-files', filename), 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    f.write(chunk)
        except Exception as e:
            return web.Response(text=f"Error uploading file: {str(e)}", status=500)
        livestream_server.load_video_list()
        return web.Response(text=f"Uploaded {filename} ({size} bytes)")
    return web.Response(text="No video file received", status=400)


async def remove_video(request):
    session = await get_session(request)
    if 'user_id' not in session:
        return web.Response(text='Unauthorized', status=401)

    livestream_server = request.app['livestream_server']
    data = await request.post()
    filename = data.get('filename')
    if filename:
        try:
            file_path = os.path.join('mp4-files', filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                livestream_server.load_video_list()
                return web.Response(text=f"Removed {filename}")
            else:
                return web.Response(text=f"File {filename} not found", status=404)
        except Exception as e:
            return web.Response(text=f"Error removing file: {str(e)}", status=500)
    return web.Response(text="Filename not provided", status=400)


def setup_admin_routes(app, livestream_server):
    app['livestream_server'] = livestream_server
    app.router.add_get("/admin", admin_panel)
    app.router.add_post("/admin/add_video", add_video)
    app.router.add_post("/admin/remove_video", remove_video)
