#!/usr/bin/env bash
# Fetch the pinned similarity corpora into one directory.
#
# Each checkout is a shallow, sparse clone at the exact commit named in
# benchmarks/similarity/corpus.py. Nothing here is committed; the
# benchmark's committed artifact is the label file.
set -euo pipefail

DEST=${1:?usage: fetch_similarity_corpora.sh <dest-dir>}
mkdir -p "$DEST"

fetch() {
  local name=$1 url=$2 sha=$3 sparse=$4
  local dir="$DEST/$name"
  if [ -d "$dir/.git" ] && [ "$(git -C "$dir" rev-parse HEAD)" = "$sha" ]; then
    echo "$name already at $sha"
    return
  fi
  rm -rf "$dir"
  mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" remote add origin "$url"
  git -C "$dir" sparse-checkout init --cone
  git -C "$dir" sparse-checkout set "$sparse"
  git -C "$dir" fetch -q --depth 1 origin "$sha"
  git -C "$dir" checkout -q FETCH_HEAD
  echo "$name at $(git -C "$dir" rev-parse HEAD)"
}

fetch home-assistant https://github.com/home-assistant/core \
  759e4658f40b3ccb671d418b8a0ed95224bf4561 homeassistant/components
fetch airflow https://github.com/apache/airflow \
  3adbbe1c58e4532df1964cb7794805e763816ee8 providers
fetch django https://github.com/django/django \
  fe0a859f537d4238cf49fca39073513206f83122 django
