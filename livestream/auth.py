import logging
import aiosqlite
import bcrypt
from aiohttp import web
from aiohttp_session import get_session
import json

DATABASE = 'users.db'

logger = logging.getLogger(__name__)


async def init_db(app):
    try:
        async with aiosqlite.connect('users.db') as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT 0
                )
            ''')
            await db.commit()

            # Check if admin user exists, if not create it
            async with db.execute('SELECT * FROM users WHERE username = ?', ('ben',)) as cursor:
                if await cursor.fetchone() is None:
                    hashed_password = bcrypt.hashpw(
                        '1234'.encode(), bcrypt.gensalt())
                    await db.execute(
                        'INSERT INTO users (username, password, email, is_admin) VALUES (?, ?, ?, ?)',
                        ('ben', hashed_password, 'admin@example.com', True)
                    )
                    await db.commit()
                    logger.info("Admin user 'ben' created successfully")
                else:
                    logger.info("Admin user 'ben' already exists")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise


async def register(request):
    data = await request.json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')

    if not username or not password or not email:
        return web.json_response({'success': False, 'message': 'Missing required fields'}, status=400)

    hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    try:
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(
                'INSERT INTO users (username, password, email) VALUES (?, ?, ?)',
                (username, hashed_password, email)
            )
            await db.commit()
        return web.json_response({'success': True, 'message': 'User registered successfully'})
    except aiosqlite.IntegrityError:
        return web.json_response({'success': False, 'message': 'Username or email already exists'}, status=400)


async def login(request):
    try:
        data = await request.json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return web.json_response({'success': False, 'message': 'Missing username or password'}, status=400)

        async with aiosqlite.connect('users.db') as db:
            async with db.execute('SELECT * FROM users WHERE username = ?', (username,)) as cursor:
                user = await cursor.fetchone()

        if user and bcrypt.checkpw(password.encode(), user[2]):
            session = await get_session(request)
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['is_admin'] = bool(user[4])
            return web.json_response({
                'success': True,
                'message': 'Logged in successfully',
                'isAdmin': bool(user[4])
            })
        else:
            return web.json_response({'success': False, 'message': 'Invalid username or password'}, status=401)
    except Exception as e:
        logger.error(f"Error during login: {str(e)}")
        return web.json_response({'success': False, 'message': 'An error occurred during login'}, status=500)


async def logout(request):
    session = await get_session(request)
    session.clear()
    return web.json_response({'success': True, 'message': 'Logged out successfully'})


async def get_profile(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        return web.json_response({'success': False, 'message': 'Not logged in'}, status=401)

    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute('SELECT id, username, email, is_admin FROM users WHERE id = ?', (user_id,)) as cursor:
            user = await cursor.fetchone()

    if user:
        return web.json_response({
            'success': True,
            'profile': {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'is_admin': bool(user[3])
            }
        })
    else:
        return web.json_response({'success': False, 'message': 'User not found'}, status=404)


async def update_profile(request):
    session = await get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        return web.json_response({'success': False, 'message': 'Not logged in'}, status=401)

    data = await request.json()
    email = data.get('email')

    if not email:
        return web.json_response({'success': False, 'message': 'Missing email'}, status=400)

    async with aiosqlite.connect(DATABASE) as db:
        try:
            await db.execute('UPDATE users SET email = ? WHERE id = ?', (email, user_id))
            await db.commit()
            return web.json_response({'success': True, 'message': 'Profile updated successfully'})
        except aiosqlite.IntegrityError:
            return web.json_response({'success': False, 'message': 'Email already in use'}, status=400)


def setup_auth(app):
    app.on_startup.append(init_db)
    app.router.add_post('/register', register)
    app.router.add_post('/login', login)
    app.router.add_post('/logout', logout)
    app.router.add_get('/profile', get_profile)
    app.router.add_put('/profile', update_profile)
