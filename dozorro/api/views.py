from rapidjson import loads, dumps
from aiohttp.web import HTTPNotFound, View, json_response
from .backend import get_list, get_many, put_item
from .validate import validate_sign, validate_form, validate_comment


class ListView(View):
    async def get(self):
        offset = self.request.GET.get('offset', None)
        limit = int(self.request.GET.get('limit', None) or 100)
        if 1 > limit > 1000:
            limit = 100
        items_list, next_offset = await get_list(
            self.request.app['db'],
            offset, limit)
        data = {'data': items_list}
        if next_offset:
            data['next_page'] = {'offset': next_offset}
        return json_response(data, dumps=dumps)

    async def post(self):
        return await self.put()

    async def put(self):
        body = await self.request.content.read()
        data = loads(body)
        app = self.request.app
        await validate_sign(data, app)
        model = data['envelope']['model']
        if model == 'form':
            await validate_form(data['envelope'], app)
        elif model == 'comment':
            await validate_comment(data['envelope'], app)
        else:
            raise ValueError('bad model name')
        await put_item(app['db'], data)
        url = app.router['item'].url_for(item_id=data['id'])
        headers = [('Location', url.path)]
        res = {'created': 1}
        return json_response(res, status=201, headers=headers, dumps=dumps)


class ItemView(View):
    async def get(self):
        item_id = self.request.match_info['item_id']
        if len(item_id) < 32:
            raise ValueError('bad id')
        items_list = item_id.split(',')
        if len(items_list) > 3300 or len(items_list) > 100:
            raise ValueError('too many ids')
        items_list = await get_many(self.request.app['db'], items_list)
        if not items_list:
            raise HTTPNotFound()
        data = {'data': items_list}
        return json_response(data, dumps=dumps)


def setup_routes(app, prefix='/api/v1'):
    app.router.add_route('*', prefix + '/data', ListView, name='list')
    app.router.add_route('GET', prefix + '/data/{item_id}', ItemView, name='item')
