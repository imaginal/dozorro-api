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

logger = logging.getLogger('dozorro.api.sync_tenders')


class FakeApp(dict):
    def __init__(self, loop):
        self.loop = loop


class Client(object):
    session = None

    @classmethod
    async def create(cls, config, loop, params={}):
        self = Client()
        self.api_url = config['url']
        self.params = {
            'feed': config.get('feed', 'changes'),
            'limit': config.get('limit', '1000'),
            'mode': config.get('mode', '_all_'),
            'descending': config.get('descending', '1')
        }
        self.params.update(params)
        if not cls.session:
            base_timeout = int(config.get('timeout', 30))
            cls.session = aiohttp.ClientSession(loop=loop,
                        conn_timeout=base_timeout,
                        read_timeout=base_timeout,
                        raise_for_status=True)
            self.session = cls.session
        await self.init_session_cookie()
        return self

    @classmethod
    async def close(cls):
        if cls.session and not cls.session.closed:
            logger.info("Close session")
            await cls.session.close()
            cls.session = None

    async def init_session_cookie(self):
        async with self.session.head(url=self.api_url, params=self.params) as resp:
            await resp.text()

    async def get_tenders(self):
        async with self.session.get(url=self.api_url, params=self.params) as resp:
            data = await resp.json()
            if 'next_page' in data:
                self.params['offset'] = data['next_page']['offset']

        return data['data']


async def save_tender(db, tender):
    try:
        await db.check_exists(tender['id'], table='tenders')
        return 0
    except AssertionError:
        await db.put_item(tender, table='tenders')
        return 1


async def run_once(app, loop, steps_back=1, query_limit=2000):
    db = await backend.init_engine(app)
    config = app['config']['client']

    if 'query_limit' in config:
        query_limit = int(config['query_limit'])
    if 'steps_back' in config:
        steps_back = int(config['steps_back'])

    fwd_client = await Client.create(config, loop)
    bwd_client = await Client.create(config, loop)

    for _ in range(steps_back):
        await fwd_client.get_tenders()
        await asyncio.sleep(0.1)
    fwd_client.params.pop('descending')
    bwd_list = True

    while loop.is_running() and query_limit > 0:
        fwd_list = await fwd_client.get_tenders()
        if bwd_list:
            bwd_list = await bwd_client.get_tenders()

        if not fwd_list and not bwd_list:
            query_limit -= 1
            logger.info('Nothing for update, query_limit %d', query_limit)
            await asyncio.sleep(10)
            continue

        if fwd_list:
            updated = 0
            for tender in fwd_list:
                updated += await save_tender(db, tender)

            logger.info('Forward fetched %d updated %d last %s',
                len(fwd_list), updated, tender.get('dateModified'))

        if bwd_list:
            updated = 0
            for tender in bwd_list:
                updated += await save_tender(db, tender)

            logger.info('Backward fetched %d updated %d last %s',
                len(bwd_list), updated, tender.get('dateModified'))

        await asyncio.sleep(1)


async def run_loop(loop, config='config/api.yaml'):
    if len(sys.argv) > 1:
        config = sys.argv[1]

    app = FakeApp(loop)
    app['config'] = utils.load_config(config)

    while loop.is_running():
        try:
            await run_once(app, loop)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception('Unhandled Exception')
            await Client.close()
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
