# PyScript Config

PyScript's configuration is fully [documented](https://docs.pyscript.net/2025.2.2/user-guide/configuration/) in the PyScript documentation. Configuration for Frontage simply requires adding the Frontage runtime files (see [Installation](../installation.md)) and Morphdom:

```JSON
{
  "name": "Frontage Tutorial",
  "debug": true,
  "packages": [
    "./frontage-{{project_version}}-py3-none-any.whl"
  ],
  "js_modules": {
    "main": {
      "https://cdn.jsdelivr.net/npm/morphdom@2.7.4/+esm": "morphdom"
    }
  }
}
```