路由匹配需要忽略开头和结尾的斜杠，内部空段保持原样；/users/ 和 users 应匹配，/users/1 不能匹配 /users。调查 router.py 和 segments.py 的调用关系。
