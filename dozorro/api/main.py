import os
import argparse
from aiohttp import web
from asyncio import get_event_loop
from dozorro.api import backend, middleware, utils, views


async def shutdown_app(app):
    if 'db' in app:
        await app['db'].close()
    if 'tenders' in app:
        await app['tenders'].close()
    if 'archive' in app:
        await app['archive'].close()


async def init_app(config=None):
    if not config:
        config = os.getenv('API_CONFIG')
    if not config:
        raise ValueError('API_CONFIG not set')
    if isinstance(config, str):
        config = utils.load_config(config)
    backend_middleware = backend.get_middleware(config)
    middlewares = [middleware.error_middleware]
    if backend_middleware:
        middlewares.append(backend_middleware)
    app = web.Application(middlewares=middlewares)
    app['config'] = config
    await backend.init_engine(app)
    app.on_shutdown.append(shutdown_app)
    if not app['config'].get('readonly'):
        loop = get_event_loop()
        await utils.create_client(app, loop)
        await utils.load_keyring(app)
        await utils.load_schemas(app)
    views.setup_routes(app)
    return app


def main():                                 # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--sock')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()

    loop = get_event_loop()
    app = loop.run_until_complete(init_app(args.config))
    web.run_app(app, path=args.sock, host=args.host, port=args.port)


if __name__ == '__main__':                  # pragma: no cover
    main()
