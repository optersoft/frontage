# os: the environment, and nothing else — there is no file system here. Values are the
# machine's, so this asserts shape rather than content.
import os

print(os.name, repr(os.sep), repr(os.linesep))
print(os.getenv("PATH") is not None, os.environ["PATH"] == os.getenv("PATH"))
print(os.getenv("FRONTAGE_NOT_SET_3f9a"), os.getenv("FRONTAGE_NOT_SET_3f9a", "fallback"))
print("FRONTAGE_NOT_SET_3f9a" in os.environ, os.environ.get("FRONTAGE_NOT_SET_3f9a", "d"))
print(len(os.environ) > 0, all(isinstance(k, str) and isinstance(v, str) for k, v in os.environ.items()))
