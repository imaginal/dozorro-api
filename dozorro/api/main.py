import argparse
import rapidjson as json
from asyncio import get_event_loop
from aiohttp import web, ClientSession
from . import backend, middleware, utils, views


async def cleanup(app):
    await app['db'].close()


async def init_app(loop, config=None):
    if not config:
        config = 'config/api.yaml'
    middlewares = [
        backend.database_middleware,
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


async def init_tables(loop, config, root_key):
    if not config:
        config = 'config/api.yaml'
    app = utils.FakeApp(loop)
    app['config'] = utils.load_config(config)
    with open(root_key) as fp:
        key = json.loads(fp.read())
    assert key['envelope']['model'] == 'admin/pubkey'
    await backend.init_engine(app)
    await app['db'].init_tables()
    await app['db'].put_item(key)


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
    parser.add_argument('--config')
    parser.add_argument('root_key')
    args = parser.parse_args()
    loop = get_event_loop()
    loop.run_until_complete(init_tables(loop, args.config, args.root_key))
    utils.logger.info("Tables created")


def cdb_put():
    parser = argparse.ArgumentParser()
    parser.add_argument('signed_json')
    parser.add_argument('api_url', nargs='?', default='127.0.0.1:8400')
    args = parser.parse_args()
    loop = get_event_loop()
    loop.run_until_complete(put_data(args.signed_json, args.api_url))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--path')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()

    loop = get_event_loop()
    app = loop.run_until_complete(init_app(loop, args.config))
    web.run_app(app, path=args.path, port=args.port)


if __name__ == '__main__':
    main()
