#!/usr/bin/env bash

set -euo pipefail

uv lock "$@"
uv export --quiet --locked --extra dev --format pylock.toml --no-header --output-file pylock.toml
