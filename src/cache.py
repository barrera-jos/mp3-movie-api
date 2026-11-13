import json
import logging

import fakeredis

logger = logging.getLogger(__name__)


class MovieCache:
    def __init__(self):
        self._responses = {}

    def get(self, limit):
        """Return the cached response for limit, or None."""
        return self._responses.get(limit)

    def set(self, limit, response):
        """Store a response for limit."""
        self._responses[limit] = response

    def invalidate(self):
        """Remove all cached responses."""
        self._responses.clear()