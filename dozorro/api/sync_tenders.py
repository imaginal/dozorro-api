import sys
import yaml
import signal
import logging
import asyncio
import aiohttp
import rapidjson
import logging.config
from functools import partial
from . import backend, utils

logger = logging.getLogger(__name__)


class FakeApp(dict):
    def __init__(self, loop):
        self.loop = loop

class Client(object):
    def __init__(self, config):
        self.api_url = config['url']
        self.params = {
            'feed': config.get('feed', 'changes'),
            'limit': config.get('limit', '1000'),
            'mode': config.get('mode', '_all_'),
            'descending': config.get('descending', '1')
        }
        self.timeout = int(config.get('timeout', 30))
        self.session = None

    def __del__(self):
        if self.session:
            self.session.close()

    async def async_init(self, loop, params={}):
        self.session = aiohttp.ClientSession(loop=loop)

        async with self.session.head(
                url=self.api_url,
                params=self.params,
                timeout=self.timeout) as resp:
            assert resp.status == 200

        self.params.update(params)

        return self

    async def get_tenders(self):
        async with self.session.get(
                url=self.api_url,
                params=self.params,
                timeout=self.timeout) as resp:
            data = await resp.json()
            if 'next_page' in data:
                self.params['offset'] = data['next_page']['offset']

        return data['data']


async def save_tender(db, tender):
    try:
        await db.check_exists(tender['id'], table='tender')
        return 0
    except AssertionError:
        await db.put_item(tender, table='tender')
        return 1


async def run_once(app, loop, query_limit=3000):
    db = await backend.init_engine(app)
    config = app['config']['client']

    fwd_client = await Client(config).async_init(loop)
    bwd_client = await Client(config).async_init(loop)

    await fwd_client.get_tenders()
    fwd_client.params.pop('descending')
    bwd_list = True

    while loop.is_running() and query_limit > 0:
        fwd_list = await fwd_client.get_tenders()
        if bwd_list:
            bwd_list = await bwd_client.get_tenders()

        if not fwd_list and not bwd_list:
            query_limit -= 1
            await asyncio.sleep(10)
            continue

        tender = {}
        updated = 0

        for tender in bwd_list:
            updated += await save_tender(db, tender)

        logger.info('Backward client fetched %d updated %d last %s',
            len(bwd_list), updated, tender.get('dateModified'))

        tender = {}
        updated = 0

        for tender in fwd_list:
            updated += await save_tender(db, tender)

        logger.info('Forward client fetched %d updated %d last %s',
            len(fwd_list), updated, tender.get('dateModified'))

        await asyncio.sleep(1)


async def run_loop(loop, config='config/api.yaml'):
    if len(sys.argv) > 1:
        config = sys.argv[1]

    app = FakeApp(loop)
    utils.load_config(app, config)

    while loop.is_running():
        try:
            await run_once(app, loop)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception('Unhandled Exception')
            await asyncio.sleep(10)

    logger.info('Loop closed.')


def shutdown(loop):
    for task in asyncio.Task.all_tasks(loop):
        task.cancel()


def main():
    loop = asyncio.get_event_loop()
    shutdown_loop = partial(shutdown, loop)
    loop.add_signal_handler(signal.SIGHUP, shutdown_loop)
    loop.add_signal_handler(signal.SIGTERM, shutdown_loop)
    loop.run_until_complete(run_loop(loop))
    loop.close()

if __name__ == '__main__':
    main()
