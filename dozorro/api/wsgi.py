from asyncio import get_event_loop
from .main import init_app


loop = get_event_loop()
app = loop.run_until_complete(init_app(loop))

