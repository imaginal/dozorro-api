
DEFAULT_ENGINE = 'rethink'


def get_middleware(config):
    engine_name = config['database'].get('engine', DEFAULT_ENGINE)
    if engine_name == 'rethink':
        from .rethink.middleware import database_middleware
        return database_middleware
    elif engine_name == 'mongo':
        from .mongo.middleware import database_middleware
        return database_middleware
    return None


async def init_engine(app):
    config = app['config']
    engine_name = config['database'].get('engine', DEFAULT_ENGINE)
    if engine_name == 'mongo':
        from .mongo.engine import MongoEngine
        engine = MongoEngine()
    elif engine_name == 'rethink':
        from .rethink.engine import RethinkEngine
        engine = RethinkEngine()
    else:
        raise ValueError('unknown database engine: %s' % engine_name)
    await engine.init_engine(app)
    return engine
