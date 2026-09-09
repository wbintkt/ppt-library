"""小容量、进程内缓存；键包含模型/内容版本，不缓存失败或整页元数据。"""
import copy
import time
from collections import OrderedDict
from threading import Lock


class TTLCache:
    def __init__(self, capacity=128, ttl=300):
        self.capacity, self.ttl = capacity, ttl
        self._items = OrderedDict()
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            row = self._items.get(key)
            if row is None:
                return None
            expires, value = row
            if expires <= time.monotonic():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(value)

    def put(self, key, value):
        with self._lock:
            self._items[key] = (time.monotonic() + self.ttl, copy.deepcopy(value))
            self._items.move_to_end(key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def clear(self):
        with self._lock:
            self._items.clear()
