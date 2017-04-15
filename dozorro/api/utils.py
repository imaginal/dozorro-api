from glob import glob
from rapidjson import loads
import logging

LOG_FORMAT = '%(asctime)-15s %(levelname)s %(message)s'

logger = logging.getLogger(__name__)


def load_owners(app, path='private/keyring'):
    keyring = {}
    for fn in glob(path + '/*pubkey.json'):
        data = loads(open(fn, 'rb').read())
        payload = data['envelope']['payload']
        owner = payload['owner']
        keyring[owner] = payload
    app['keyring'] = keyring
    logging.info("Loaded {} keys".format(len(keyring)))


def load_schemas(app, path='private/schemas'):
    schemas = {}
    comment = loads(open(path + '/comment.json', 'rb').read())
    for fn in glob(path + '/*.json'):
        data = loads(open(fn, 'rb').read())
        if 'definitions' not in data:
            data['definitions'] = comment['definitions']
        name = fn.rsplit('/', 1)[1].replace('.json', '')
        schemas[name] = data
    app['schemas'] = schemas
    logging.info("Loaded {} schemas".format(len(schemas)))
