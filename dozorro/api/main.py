from asyncio import get_event_loop
from aiohttp import web
from . import backend, middleware, utils, views


async def cleanup(app):
    await app['db'].close()


async def init_app(loop, config='config/api.yaml'):
    middlewares = [
        # backend.database_middleware,
        middleware.error_middleware
    ]
    app = web.Application(loop=loop, middlewares=middlewares)
    app['config'] = utils.load_config(config)
    await backend.init_engine(app)
    app.on_cleanup.append(cleanup)
    await utils.load_keyring(app)
    await utils.load_schemas(app)
    views.setup_routes(app)
    return app


def main(run=True):
    loop = get_event_loop()
    app = loop.run_until_complete(init_app(loop))
    if run:
        port = app['config'].get('port', 8410)
        web.run_app(app, port=port)
    return app


if __name__ == '__main__':
    main()
