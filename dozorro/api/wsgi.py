from os import environ
from asyncio import get_event_loop
from .main import init_app

loop = get_event_loop()
conf = environ.get('API_CONFIG')
app = loop.run_until_complete(init_app(loop, conf))
