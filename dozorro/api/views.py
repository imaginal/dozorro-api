import re
from rapidjson import loads, dumps
from aiohttp.web import HTTPNotFound, View, json_response
from .validate import validate_envelope, validate_schema

HEX_LIST = re.compile(r'^[0-9a-f,]{32,3300}$')


class ListView(View):
    @staticmethod
    def offset_args(offset, reverse):
        if reverse:
            return {'offset': offset, 'reverse': '1'}
        return {'offset': offset}

    async def get(self):
        args = self.request.GET
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

    async def post(self):
        return await self.put()

    async def put(self):
        body = await self.request.content.read()
        data = loads(body)
        app = self.request.app

        validate_envelope(data, app['keyring'])
        await validate_schema(data['envelope'], app)

        if self.request.GET.get('nosave', False):
            resp = {'validated': 1, 'created': 0}
            return json_response(resp, dumps=dumps)

        await app['db'].put_item(data)
        url = app.router['item_view'].url_for(item_id=data['id'])
        headers = [('Location', url.path)]
        resp = {'created': 1}
        return json_response(resp, status=201, headers=headers, dumps=dumps)


class ItemView(View):
    async def get(self):
        item_id = self.request.match_info['item_id']
        if len(item_id) > 3300:
            raise ValueError('bad id length')
        if not HEX_LIST.match(item_id):
            raise ValueError('bad id chars')

        many_ids = item_id.split(',')
        if len(many_ids) > 100:
            raise ValueError('too many ids')

        db = self.request.app['db']
        items_list = await db.get_many(many_ids)
        if not items_list:
            raise HTTPNotFound()

        resp = {'data': items_list}
        # TODO make cache-control configurable
        headers = [('Cache-Control', 'public, max-age=31536000')]
        return json_response(resp, headers=headers, dumps=dumps)


def setup_routes(app, prefix='/api/v1'):
    app.router.add_route('*', prefix + '/data', ListView, name='list_view')
    app.router.add_route('*', prefix + '/data/{item_id}', ItemView, name='item_view')
