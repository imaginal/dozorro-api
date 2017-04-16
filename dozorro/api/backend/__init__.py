from .rethink.engine import RethinkEngine
from .rethink.middleware import database_middleware


async def init_engine(app):
    engine = RethinkEngine()
    await engine.init_engine(app)
    return engine
