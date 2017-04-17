import glob
import yaml
import logging
import logging.config
import rapidjson as json

logger = logging.getLogger(__name__)


async def load_keyring(app):
    path = app['config']['keyring']
    keyring = {}
    for fn in glob.glob(path + '/*.json'):
        data = json.loads(open(fn, 'rb').read())
        payload = data['envelope']['payload']
        owner = payload['owner']
        keyring[owner] = payload
        await app['db'].check_exists(data['id'])
    app['keyring'] = keyring
    logger.info('Loaded {} keys'.format(len(keyring)))


async def load_schemas(app):
    path = app['config']['schemas']
    schemas = {}
    comment = json.loads(open(path + '/comment.json', 'rb').read())
    for fn in glob.glob(path + '/*.json'):
        data = json.loads(open(fn, 'rb').read())
        if 'definitions' not in data:
            data['definitions'] = comment['definitions']
        name = fn.rsplit('/', 1)[1].replace('.json', '')
        schemas[name] = data
    app['schemas'] = schemas
    logger.info('Loaded {} schemas'.format(len(schemas)))


def load_config(filename, app=None, configure_logging=True):
    config = yaml.load(open(filename))
    if 'logging' in config and configure_logging:
        logconf = yaml.load(open(config['logging']))
        logging.config.dictConfig(logconf)
    logger.info('Load config from {}'.format(filename))
    return config
