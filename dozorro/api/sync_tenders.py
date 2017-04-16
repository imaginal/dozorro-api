import sys
import logging
import asyncio
import aiohttp
import rapidjson

from .backend import init_engine


logger = logging.getLogger(__name__)


class Client(object):
    def __init__(self, conf):
        self.api_url = conf['url']
        self.params = {
            # 'feed': conf.get('feed', 'changes'),
            'limit': conf.get('limit', '1000'),
            'mode': conf.get('mode', '_all_'),
            'descending': conf.get('descending', '')
        }
        self.timeout = int(conf.get('timeout', 30))
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
    if tender['dateModified'] < '2016-04':
        return 0
    try:
        await db.check_exists(tender['id'], table='tender')
        return 0
    except AssertionError:
        await db.put_item(tender, table='tender')
        return 1


async def run_once(conf, loop, query_limit=1000):
    app = {}
    db = await init_engine(app)

    fwd_client = await Client(conf).async_init(loop)
    bwd_client = await Client(conf).async_init(loop)

    await fwd_client.get_tenders()
    fwd_client.params.pop('descending')
    bwd_list = True

    # retry each 1000 empty queries, its about 10 hr
    while loop.is_running() and query_limit:
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

        logger.info("Backward client fetched %d updated %d last %s",
            len(bwd_list), updated, tender.get('dateModified'))

        tender = {}
        updated = 0

        for tender in fwd_list:
            updated += await save_tender(db, tender)

        logger.info("Forward client fetched %d updated %d last %s",
            len(fwd_list), updated, tender.get('dateModified'))

        await asyncio.sleep(1)


async def run_loop(loop):
    conf = {
        'url': 'https://public.api.openprocurement.org/api/2.3/tenders',
        'descending': '1'
    }

    while loop.is_running():
        try:
            await run_once(conf, loop)
        except Exception as e:
            logger.exception("run_once: %s", e)
            await asyncio.sleep(50)

    logger.info("Loop closed.")


def main():
    log_format = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format)

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run_loop(loop))
    except KeyboardInterrupt:
        loop.stop()
    finally:
        loop.close()

if __name__ == '__main__':
    main()
