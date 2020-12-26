import glob
import yaml
import aiohttp
import iso8601
import logging
import logging.config
import rapidjson as json

logger = logging.getLogger(__name__)


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
            headers = {'User-Agent': 'dozorro.api/0.3.1'}
            base_timeout = int(config.get('timeout', 30))
            timeout = aiohttp.ClientTimeout(base_timeout)
            cls.session = aiohttp.ClientSession(loop=loop,
                        headers=headers,
                        timeout=timeout,
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

    async def get_tender(self, tender_id):
        tender_uri = "{}/{}".format(self.api_url, tender_id)
        async with self.session.get(tender_uri) as resp:
            data = await resp.json()
        return data['data']


async def create_client(app, loop):
    if 'tenders' in app['config']:
        config = app['config']['tenders']
        app['tenders'] = await Client.create(config, loop)
    if 'archive' in app['config']:
        config = app['config']['archive']
        app['archive'] = await Client.create(config, loop)


async def load_keyring(app):
    path = app['config']['keyring']
    keyring = {}
    for fn in glob.glob(path + '/*.json'):
        logger.debug('Load pubkey {}'.format(fn))
        with open(fn, 'rb') as fp:
            data = json.loads(fp.read())
        model = data['envelope']['model']
        assert model == 'admin/pubkey', 'bad key model'
        payload = data['envelope']['payload']
        payload['validSince'] = iso8601.parse_date(payload['validSince'])
        payload['validTill'] = iso8601.parse_date(payload['validTill'])
        owner = payload['owner']
        if owner not in keyring:
            keyring[owner] = []
        await app['db'].check_exists(data['id'])
        keyring[owner].append(payload)
    app['keyring'] = keyring
    logger.info('Loaded {} keys'.format(len(keyring)))


async def load_schemas(app):
    path = app['config']['schemas']
    schemas = {}
    comment = {}
    for fn in glob.glob(path + '/comment.json'):
        logger.debug('Load comment {}'.format(fn))
        with open(fn, 'rb') as fp:
            root = json.loads(fp.read())
        payload = root['envelope']['payload']
        comment = payload['schema']
    for fn in glob.glob(path + '/*.json'):
        logger.debug('Load schema {}'.format(fn))
        with open(fn, 'rb') as fp:
            root = json.loads(fp.read())
        model = root['envelope']['model']
        assert model == 'admin/schema', 'bad schema model'
        payload = root['envelope']['payload']
        data = payload['schema']
        if 'definitions' not in data:
            data['definitions'] = comment['definitions']
        model, schema = payload['model'].split('/')
        await app['db'].check_exists(root['id'])
        schemas[schema] = data
    app['schemas'] = schemas
    logger.info('Loaded {} schemas'.format(len(schemas)))


def load_config(filename, app=None, configure_logging=True):
    with open(filename) as fp:
        config = yaml.safe_load(fp)
    if 'logging' in config and configure_logging:
        with open(config['logging']) as fp:
            logconf = yaml.safe_load(fp)
        logging.config.dictConfig(logconf)
    # log only after logging system initialized
    logger.info('Load config from {}'.format(filename))
    return config
