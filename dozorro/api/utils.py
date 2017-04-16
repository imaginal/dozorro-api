import glob
import yaml
import logging
import logging.config
import rapidjson as json

logger = logging.getLogger(__name__)


def load_keyring(app):
    path = app['config']['keyring']
    keyring = {}
    for fn in glob.glob(path + '/*.json'):
        data = json.loads(open(fn, 'rb').read())
        payload = data['envelope']['payload']
        owner = payload['owner']
        keyring[owner] = payload
    app['keyring'] = keyring
    logging.info('Loaded {} keys'.format(len(keyring)))


def load_schemas(app):
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
    logging.info('Loaded {} schemas'.format(len(schemas)))


def load_config(app, filename):
    config = yaml.load(open(filename))
    if 'logging' in config:
        logging.config.fileConfig(config['logging'],
            disable_existing_loggers=False)
    logging.info('Load config from {}'.format(filename))
    app['config'] = config
