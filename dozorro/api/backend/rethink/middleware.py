from rethinkdb.errors import ReqlDriverError


async def database_middleware(app, handler):
    async def middleware_handler(request):
        try:
            request.app['db'].check_open()
        except ReqlDriverError:
            request.app['db'] = await request.app['db'].reconnect(False)
        response = await handler(request)
        return response
    return middleware_handler
