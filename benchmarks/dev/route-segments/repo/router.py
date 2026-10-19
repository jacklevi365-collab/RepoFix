from segments import split_path
def matches(pattern, path):
    return split_path(pattern) == split_path(path)
