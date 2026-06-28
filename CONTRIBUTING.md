# Development

## Install dependencies

In order to set up the project, use Python and Node.js/npm and install the
dependencies from `requirements.txt` and `package-lock.json`. If you use
micromamba, activate the project environment first:

```shell
$ micromamba activate beman
```

```shell
$ make install
```

The staged site also builds Antora documentation. Pandoc converts Markdown into
AsciiDoc, and MrDocs generates API reference pages. Make sure `pandoc` and
`mrdocs` are available on `PATH` before running `make start` or `make build`.

Library docs are configured in `beman_libraries_to_import.yaml`. Keep library
repos adjacent to this repo (`../optional`, `../execution`, ...). Add or edit a
library there, then run `make start`.

You can verify MkDocs is properly installed using

```shell
$ python -m mkdocs --version
```

If this fails, please check manual instructions:

<details>
<summary> Dev Container instructions </summary>

This project includes a development container configuration for VS Code. To use it:

1. Install [Visual Studio Code](https://code.visualstudio.com/) and the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
2. Open the project in VS Code.
3. When prompted, reopen the project in the dev container.
4. The container will automatically install dependencies and set up the environment.
5. Go to the [Start local server](#start-local-server) section.

</details>

<details>
<summary> Linux instructions</summary>

```shell
$ sudo apt install python3 python3-pip
$ python3 -m pip install -r requirements.txt
```

</details>

<details>
<summary> MacOS instructions</summary>

```shell
$ brew install python
$ python3 -m pip install -r requirements.txt
```

</details>

<details>
<summary> Windows instructions</summary>

```shell
$ winget install Python.Python.3
$ python -m pip install -r requirements.txt
```

</details>

## Start local server

To start a local development server, run:

```shell
$ make start
```

If everything is properly installed, the command builds the composed MkDocs +
Antora site and serves it on http://127.0.0.1:8000/.

Rerun `make start` after making documentation changes. The local server serves
the static composed output; it is not a live-reloading MkDocs-only server.

## Generate static content for GitHub Pages deployment

To generate static from the project that can be served using any static contents hosting service (like `gh-pages`).

```shell
$ make build
```
