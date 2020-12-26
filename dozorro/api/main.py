import os
import argparse
import rapidjson as json
from asyncio import get_event_loop
from aiohttp import web, ClientSession
from . import backend, middleware, utils, views


async def cleanup(app):
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
    app.on_cleanup.append(cleanup)
    if not app['config'].get('readonly'):
        loop = get_event_loop()
        await utils.create_client(app, loop)
        await utils.load_keyring(app)
        await utils.load_schemas(app)
    views.setup_routes(app)
    return app


async def init_tables(loop, config, root_key, dropdb=False):
    app = utils.FakeApp(loop)
    app['config'] = utils.load_config(config)
    with open(root_key) as fp:
        key = json.loads(fp.read())
    assert key['envelope']['model'] == 'admin/pubkey'
    await backend.init_engine(app)
    await app['db'].init_tables(dropdb)
    await app['db'].put_item(key)
    await cleanup(app)


async def put_data(signed_json, api_url):
    if ':' not in api_url:
        api_url += ':8400'
    if '/api/' not in api_url:
        api_url += '/api/v1/data'
    if '://' not in api_url:
        api_url = 'http://' + api_url
    with open(signed_json) as fp:
        text = fp.read()
        item = json.loads(text)
    headers = {
        'Content-type': 'application/json',
        'User-agent': 'cdb_put by ' + item['envelope']['owner']
    }
    async with ClientSession() as session:
        item_url = "{}/{}".format(api_url, item['id'])
        async with session.put(item_url, data=text, headers=headers) as resp:
            resp_text = await resp.text()
    print("PUT {} {} {}".format(item['id'], resp.status, resp_text))


def cdb_init():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dropdb', action='store_true')
    parser.add_argument('--config')
    parser.add_argument('root_key')
    args = parser.parse_args()
    loop = get_event_loop()
    loop.run_until_complete(init_tables(loop, args.config,
        args.root_key, args.dropdb))
    utils.logger.info("Tables created")


def cdb_put():
    parser = argparse.ArgumentParser()
    parser.add_argument('signed_json')
    parser.add_argument('api_url', nargs='?', default='127.0.0.1:8400')
    args = parser.parse_args()
    loop = get_event_loop()
    loop.run_until_complete(put_data(args.signed_json, args.api_url))


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
