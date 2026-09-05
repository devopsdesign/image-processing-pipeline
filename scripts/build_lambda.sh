#!/usr/bin/env bash
# Builds the Lambda deployment directory: terraform/build/
# Called by Terraform (null_resource) and by CI before `terraform apply`.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build="${root}/terraform/build"

rm -rf "${build}"
mkdir -p "${build}" "${root}/terraform/dist"

python3 -m pip install \
  --no-deps \
  --quiet \
  --target "${build}" \
  --requirement "${root}/lambda/requirements.txt"

cp "${root}/lambda/index.py" "${build}/"

echo "Lambda build ready: ${build}"
