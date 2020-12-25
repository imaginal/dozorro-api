

async def database_middleware(app, handler):
    async def middleware_handler(request):
        # await request.app['db'].check_open()
        return await handler(request)
    return middleware_handler
