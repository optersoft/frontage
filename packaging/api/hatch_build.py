"""Pin `frontage` to exactly this version.

**They are one release, and a mismatched pair does not work.** The server binary has the
runtime compiled into it, and that runtime executes `frontage`'s own modules — `reactive`,
`schema`, `view` — so a `frontage_api` built against one version and installed beside another
is not a supported combination, it is a bug report. Both wheels come from one tag, so the
honest requirement is `==`.

A metadata hook rather than a literal, because the version lives in one file
(`frontage/version.py`) and hatchling will not interpolate it into a static dependency.
"""

from hatchling.metadata.plugin.interface import MetadataHookInterface


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata):
        namespace = {}
        with open("../../frontage/version.py", encoding="utf-8") as f:
            exec(f.read(), namespace)  # noqa: S102 - our own file, two lines long
        metadata["dependencies"] = ["frontage==" + namespace["__version__"]]
