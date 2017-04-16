from .rethink.engine import RethinkEngine
from .rethink.middleware import database_middleware


async def init_engine(app):
    eclass = app['config']['database'].pop('engine')
    engine = RethinkEngine()
    await engine.init_engine(app)
    return engine
