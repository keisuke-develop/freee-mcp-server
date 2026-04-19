#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/.env}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
SECRET_NAME="${SECRET_NAME:-freee/mcp-server}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "env file not found: ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

required_vars=(
  FREEE_CLIENT_ID
  FREEE_CLIENT_SECRET
  FREEE_REFRESH_TOKEN
  FREEE_ACCESS_TOKEN
  FREEE_COMPANY_ID
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "missing required variable: ${var_name}" >&2
    exit 1
  fi
done

access_token_expires_at="${FREEE_ACCESS_TOKEN_EXPIRES_AT:-$(TZ=Asia/Tokyo date -Iseconds -d "+6 hours")}"

secret_payload=$(cat <<EOF
{"client_id":"${FREEE_CLIENT_ID}","client_secret":"${FREEE_CLIENT_SECRET}","refresh_token":"${FREEE_REFRESH_TOKEN}","access_token":"${FREEE_ACCESS_TOKEN}","access_token_expires_at":"${access_token_expires_at}","company_id":${FREEE_COMPANY_ID}}
EOF
)

if aws secretsmanager describe-secret --secret-id "${SECRET_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value \
    --secret-id "${SECRET_NAME}" \
    --region "${AWS_REGION}" \
    --secret-string "${secret_payload}"
  echo "updated secret: ${SECRET_NAME} (${AWS_REGION})"
else
  aws secretsmanager create-secret \
    --name "${SECRET_NAME}" \
    --region "${AWS_REGION}" \
    --description "freee Remote MCP Server OAuth credentials" \
    --secret-string "${secret_payload}"
  echo "created secret: ${SECRET_NAME} (${AWS_REGION})"
fi
