from os import getenv
from asyncio import get_event_loop
from .main import init_app

loop = get_event_loop()
config = getenv('API_CONFIG')
app = loop.run_until_complete(init_app(config))
