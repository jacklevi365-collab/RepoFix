class Cache:
    def __init__(self):
        self.entries = {}
    def put(self, key, value, expires_at):
        self.entries[key] = (value, expires_at)
    def get(self, key, now):
        if key not in self.entries:
            return None
        value, expiry = self.entries[key]
        if now > expiry:
            del self.entries[key]
            return None
        return value
