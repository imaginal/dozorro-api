import os
import sys
import glob
import yaml
import fcntl
import atexit
import aiohttp
import iso8601
import logging
import logging.config
import rapidjson as json

logger = logging.getLogger(__name__)


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
            headers = {'User-Agent': 'dozorro.api/0.3.1'}
            base_timeout = int(config.get('timeout', 30))
            cls.session = aiohttp.ClientSession(loop=loop,
                        headers=headers,
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

    async def get_tender(self, tender_id):
        tender_uri = "{}/{}".format(self.api_url, tender_id)
        async with self.session.get(tender_uri) as resp:
            data = await resp.json()
        return data['data']


async def load_keyring(app):
    path = app['config']['keyring']
    keyring = {}
    for fn in glob.glob(path + '/*.json'):
        logger.info('Load pubkey {}'.format(fn))
        data = json.loads(open(fn, 'rb').read())
        model = data['envelope']['model']
        assert model == 'admin/pubkey', 'bad key model'
        payload = data['envelope']['payload']
        payload['validSince'] = iso8601.parse_date(payload['validSince'])
        payload['validTill'] = iso8601.parse_date(payload['validTill'])
        owner = payload['owner']
        if owner not in keyring:
            keyring[owner] = []
        keyring[owner].append(payload)
        await app['db'].check_exists(data['id'])
    app['keyring'] = keyring
    logger.info('Loaded {} keys'.format(len(keyring)))


async def load_schemas(app):
    path = app['config']['schemas']
    schemas = {}
    comment = {}
    for fn in glob.glob(path + '/comment.json'):
        logger.info('Load comment {}'.format(fn))
        root = json.loads(open(fn, 'rb').read())
        payload = root['envelope']['payload']
        comment = payload['schema']
    for fn in glob.glob(path + '/*.json'):
        logger.info('Load schema {}'.format(fn))
        root = json.loads(open(fn, 'rb').read())
        model = root['envelope']['model']
        assert model == 'admin/schema', 'bad schema model'
        payload = root['envelope']['payload']
        data = payload['schema']
        if 'definitions' not in data:
            data['definitions'] = comment['definitions']
        model, schema = payload['model'].split('/')
        schemas[schema] = data
        await app['db'].check_exists(root['id'])
    app['schemas'] = schemas
    logger.info('Loaded {} schemas'.format(len(schemas)))


def load_config(filename, app=None, configure_logging=True):
    config = yaml.safe_load(open(filename))
    if 'logging' in config and configure_logging:
        logconf = yaml.safe_load(open(config['logging']))
        logging.config.dictConfig(logconf)
    logger.info('Load config from {}'.format(filename))
    return config


def daemonize(logfile, chdir=None):
    if os.fork() > 0:
        sys.exit(0)

    if chdir:
        os.chdir(chdir)
    os.setsid()

    if os.fork() > 0:
        sys.exit(0)

    if not logfile:
        logfile = '/dev/null'

    fout = open(logfile, 'ba+')
    ferr = open(logfile, 'ba+', 0)
    sys.stdin.close(), os.close(0)
    os.dup2(fout.fileno(), 1)
    os.dup2(ferr.fileno(), 2)


def remove_pidfile(lock_file, filename, mypid):
    if mypid != os.getpid():
        return
    lock_file.seek(0)
    if mypid != int(lock_file.read() or 0):
        return
    logger.info("Remove pidfile %s", filename)
    fcntl.lockf(lock_file, fcntl.LOCK_UN)
    lock_file.close()
    os.remove(filename)


def write_pidfile(filename):
    if not filename:
        return
    # try get exclusive lock to prevent second start
    mypid = os.getpid()
    logger.info("Save %d to pidfile %s", mypid, filename)
    lock_file = open(filename, "a+")
    fcntl.lockf(lock_file, fcntl.LOCK_EX + fcntl.LOCK_NB)
    lock_file.truncate()
    lock_file.write(str(mypid) + "\n")
    lock_file.flush()
    atexit.register(remove_pidfile, lock_file, filename, mypid)
    return lock_file
