from uuid import uuid4


class RequestContextMiddleware:
    """Tags each request with an id so related audit events can be correlated."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid4())
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
