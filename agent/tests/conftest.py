"""Shared pytest fixtures.

Async tests use the anyio pytest plugin (anyio ships it): tests marked
`@pytest.mark.anyio` get the `anyio_backend` fixture defined here.
"""

import pytest


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param
