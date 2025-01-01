# Project Name

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

A CLI application makes it easier to work with Jenkins. The program supports build using alias and multiple build for dependencies.

## Features

- Easy-to-use CLI interface
- Support YAML configuration file
- Build using alias
- Multiple build for dependencies

## Installation

### Prerequisites

- Python 3.9 or higher
- `pip` package manager


### Install from source

1. Clone the repository:

```bash
$ git clone https://github.com/hpmtrung/jenkins-bt
$ cd jenkins-bt
```

2. Create and activate the environment:

```bash
$ python -m venv .venv
$ source venv/bin/activate  # or .\venv\Scripts\activate on Windows
```

3. Install dependencies:

```bash
$ pip install -r requirements.txt
```

5. Run and check:

```bash
$ python main.py --help
```

## Usage

After installation, you can use the tool by running:

```bash
$ jenkins-bt [OPTIONS] [ARGS...]
```

The program has only one commmand with these options:

- `-f <path>`: Path to your YAML config file. Supporting both `.yaml` and `.yml` extension.
- `-s <alias>`: An alias of starting point
- `-e <alias...>`: Exclude build for aliases (optional)
- `--ignore-failed`: Skip failed build and continuing (by default is fail fast) (optional)

Run `jenkins-bt --help` for more details

### Configuration File

A configuration file should contain 4 fields:

- `endpoint`: A Jenkins server URL
- `auth`: Include Jenkins username and API token for authentication. See [how to generate API token](https://stackoverflow.com/a/45466184).
- `aliases`: A list of alias and corresponding Jenkins job name.
- `dependencies`: A list of build dependencies using aliases. Format `A: B` means `A` depends on `B` (i.e. `B` must be built before `A`)

Example:

```yaml
endpoint: http://localhost:8080

auth:
  username: ""
  api-token: ""

aliases:
  - dev-api-client: DEV-api-clients
  - dev-flight-client: DEV-flight-api-clients
  - dev-flight-search: DEV-flight-search-service
  - dev-booking: DEV-booking-service
  - dev-meta: DEV-meta-service

dependencies:
  - dev-flight-client: dev-api-client
  - dev-flight-search: dev-flight-client
  - dev-booking: dev-api-client
  - dev-meta: dev-api-client
```

## Troubleshooting

For troubleshooting, view log files that are located in the directory `$HOME/jenkins-bt-logs`.

## Limitations

The program doesn't support Jenkins SSH authentication