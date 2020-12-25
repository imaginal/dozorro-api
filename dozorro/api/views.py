import re
from rapidjson import loads, dumps
from aiohttp.web import HTTPNotFound, HTTPMethodNotAllowed, View, json_response
from .validate import ValidateError, validate_envelope, validate_schema

HEX_LIST = re.compile(r'^[0-9a-f,]{32,3300}$')


class ListView(View):
    @staticmethod
    def offset_args(offset, reverse):
        if reverse:
            return {'offset': offset, 'reverse': '1'}
        return {'offset': offset}

    async def get(self):
        args = self.request.query
        offset = args.get('offset', None)
        limit = int(args.get('limit', None) or 100)
        reverse = bool(args.get('reverse', 0))
        if limit < 1 or limit > 1000:
            limit = 100
        db = self.request.app['db']
        items_list, first, last = await db.get_list(
            offset, limit, reverse)
        resp = {'data': items_list}
        if first:
            resp['prev_page'] = ListView.offset_args(first, not reverse)
        if last:
            resp['next_page'] = ListView.offset_args(last, reverse)
        return json_response(resp, dumps=dumps)


class ItemView(View):
    async def get(self):
        item_id = self.request.match_info['item_id']
        if len(item_id) > 3300:
            raise ValidateError('bad id length')
        if not HEX_LIST.match(item_id):
            raise ValidateError('bad id chars')

        many_ids = item_id.split(',')
        if len(many_ids) > 100:
            raise ValidateError('too many ids')

        db = self.request.app['db']
        items_list = await db.get_many(many_ids)
        if not items_list:
            raise HTTPNotFound()

        resp = {'data': items_list}
        # TODO make cache-control configurable
        headers = [('Cache-Control', 'public, max-age=31536000')]
        return json_response(resp, headers=headers, dumps=dumps)

    async def put(self):
        if self.request.app['config'].get('readonly'):
            raise HTTPMethodNotAllowed(self.request.method, ['GET'])
        item_id = self.request.match_info['item_id']
        ct = self.request.headers.get('Content-Type')
        ua = self.request.headers.get('User-Agent')
        if not ct or not ct.startswith('application/json'):
            raise ValidateError('Content-Type must be application/json')

        self.request.raw_body_data = await self.request.content.read()
        data = loads(self.request.raw_body_data)
        app = self.request.app

        validate_envelope(data, app['keyring'])
        await validate_schema(data['envelope'], app)

        if item_id != data['id']:
            raise ValidateError('id in uri and data mismatch')

        if ua and ua.find(data['envelope']['owner']) < 0:
            raise ValidateError('User-Agent must include owner')

        if self.request.query.get('nosave', False):
            resp = {'validated': 1, 'created': 0}
            return json_response(resp, dumps=dumps)

        await app['db'].put_item(data)
        url = app.router['item_view'].url_for(item_id=item_id)
        headers = [('Location', url.path)]
        resp = {'created': 1}
        return json_response(resp, status=201, headers=headers, dumps=dumps)


def setup_routes(app, prefix='/api/v1'):
    app.router.add_route('*', prefix + '/data', ListView, name='list_view')
    app.router.add_route('*', prefix + '/data/{item_id}', ItemView, name='item_view')
