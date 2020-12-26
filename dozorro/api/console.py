import argparse
import rapidjson as json
from iso8601 import parse_date
from aiohttp import ClientSession
from asyncio import get_event_loop, sleep
from dozorro.api import backend, utils, validate


async def init_tables(loop, config, root_key, dropdb=False):
    app = dict()
    app['config'] = utils.load_config(config)
    with open(root_key) as fp:
        key = json.loads(fp.read())
    assert key['envelope']['model'] == 'admin/pubkey'
    await backend.init_engine(app)
    await app['db'].init_tables(dropdb)
    await app['db'].put_item(key)
    await app['db'].close()


async def put_data(signed_json, api_url):
    if ':' not in api_url:
        api_url += ':8400'  # pragma: no cover
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


def update_keyring(data, keyring):
    payload = data['envelope']['payload'].copy()
    payload['validSince'] = parse_date(payload['validSince'])
    payload['validTill'] = parse_date(payload['validTill'])
    owner = payload['owner']
    if owner not in keyring:
        keyring[owner] = []
    keyring[owner].append(payload)


def update_schemas(data, app):
    payload = data['envelope']['payload']
    model, schema = payload['model'].split('/')
    data = payload['schema']

    if 'definitions' in data and data['definitions']:
        app['definitions'].update(data['definitions'])
    else:
        data['definitions'] = app['definitions']

    assert schema not in app['schemas']
    app['schemas'][schema] = data


async def validate_data(data, app):
    model = data['envelope']['model']

    if app['keyring']:
        validate.validate_envelope(data, app['keyring'], check_date=False)

    if model == 'admin/pubkey':
        update_keyring(data, app['keyring'])
        return

    if model == 'admin/schema':
        update_schemas(data, app)
        return

    await validate.validate_schema(data['envelope'], app, check_refs=False)


async def verify_database(config, api_url, ignore_errors=False):
    app = {
        'keyring': {},
        'schemas': {},
        'definitions': {}
    }
    app['config'] = utils.load_config(config)
    await backend.init_engine(app)
    success = 0
    errors = 0
    offset = None
    while True:
        page, _, offset = await app['db'].get_list(offset)
        if not page:
            break
        pids = [p['id'] for p in page]
        items = await app['db'].get_many(pids)
        assert len(pids) == len(items)
        for pid in pids:
            for data in items:
                if pid == data['id']:
                    break
            env = data['envelope']
            try:
                await validate_data(data, app)
                success += 1
                print("OK", success, data['id'], env['date'], env['owner'], env['model'])
            except Exception as e:  # pragma: no cover
                errors += 1
                print("\033[91m" + "FAIL", errors, data['id'], env['date'], env['owner'], env['model'],
                      "\033[0m " + "ERROR:", e)
                if not ignore_errors:
                    await app['db'].close()
                    raise
        if not offset:
            break
    print("SUCCESS", success, "ERRORS", errors)
    await app['db'].close()


async def verify_api_data(api_url, ignore_errors=False, pause=0.1):
    if ':' not in api_url:
        api_url += ':8400'  # pragma: no cover
    if '/api/' not in api_url:
        api_url += '/api/v1/data'
    if '://' not in api_url:
        api_url = 'http://' + api_url
    app = {
        'keyring': {},
        'schemas': {},
        'definitions': {}
    }
    session = ClientSession()
    success = 0
    errors = 0
    offset = ''
    while True:
        list_url = api_url + '?offset=' + offset
        resp = await session.get(list_url)
        resp.raise_for_status()
        page = await resp.json()
        if not page['data']:
            break
        items_ids = ','.join([p['id'] for p in page['data']])
        items_url = api_url + '/' + items_ids
        await sleep(pause)
        resp = await session.get(items_url)
        resp.raise_for_status()
        resp_data = await resp.json()
        assert len(page['data']) == len(resp_data['data'])
        for row in page['data']:
            for data in resp_data['data']:
                if data['id'] == row['id']:
                    break
            env = data['envelope']
            try:
                await validate_data(data, app)
                success += 1
                print("OK", success, data['id'], env['date'], env['owner'], env['model'])
            except Exception as e:  # pragma: no cover
                errors += 1
                print("\033[91m" + "FAIL", errors, data['id'], env['date'], env['owner'], env['model'],
                      "\033[0m " + "ERROR:", e)
                if not ignore_errors:
                    await session.close()
                    raise
        offset = page.get('next_page', {}).get('offset')
        if not offset:
            break
    print("SUCCESS", success, "ERRORS", errors)
    await session.close()


def cdb_init():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dropdb', action='store_true')
    parser.add_argument('--config')
    parser.add_argument('root_key')
    args = parser.parse_args()
    loop = get_event_loop()
    loop.run_until_complete(init_tables(
        loop, args.config, args.root_key, args.dropdb))
    utils.logger.info("Tables created")


def cdb_put():
    parser = argparse.ArgumentParser()
    parser.add_argument('signed_json')
    parser.add_argument('api_url', nargs='?', default='127.0.0.1:8400')
    args = parser.parse_args()
    loop = get_event_loop()
    loop.run_until_complete(put_data(args.signed_json, args.api_url))


def cdb_verify():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--ignore', action='store_true')
    parser.add_argument('api_url', nargs='?', default='127.0.0.1:8400')
    args = parser.parse_args()
    loop = get_event_loop()
    if args.config:
        coro = verify_database(args.config, args.ignore)
    else:
        coro = verify_api_data(args.api_url, args.ignore)
    loop.run_until_complete(coro)
