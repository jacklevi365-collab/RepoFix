缓存条目的 expires_at 为绝对时间。now 等于 expires_at 时条目已过期；未过期条目正常返回，过期条目应删除。
