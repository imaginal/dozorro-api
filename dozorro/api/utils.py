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
        logger.info('Load pubkey {}'.format(fn))
        data = json.loads(open(fn, 'rb').read())
        model = data['envelope']['model']
        assert model == 'admin/pubkey', 'bad key model'
        payload = data['envelope']['payload']
        owner = payload['owner']
        keyring[owner] = payload
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
        model = data['envelope']['model']
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
    config = yaml.load(open(filename))
    if 'logging' in config and configure_logging:
        logconf = yaml.load(open(config['logging']))
        logging.config.dictConfig(logconf)
    logger.info('Load config from {}'.format(filename))
    return config
