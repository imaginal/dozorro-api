from asyncio import get_event_loop
from aiohttp import web
from . import backend, middleware, utils, views


async def init_app(loop):
    import logging
    logging.basicConfig(format=utils.LOG_FORMAT, level=logging.INFO)
    middlewares = [
        backend.database_middleware,
        middleware.error_middleware
    ]
    app = web.Application(loop=loop, middlewares=middlewares)
    await backend.init_engine(app)
    app.on_cleanup.append(app['db'].cleanup)
    utils.load_owners(app)
    utils.load_schemas(app)
    views.setup_routes(app)
    return app


def main(run=True):
    loop = get_event_loop()
    app = loop.run_until_complete(init_app(loop))
    if run:
        web.run_app(app, port=8410)
    return app


if __name__ == '__main__':
    main()
