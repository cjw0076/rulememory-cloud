#!/usr/bin/env bash
# One-shot Cloud Run deploy for RuleMemory Cloud.
# Run from the app/ directory AFTER you have:
#   1) gcloud auth login  &&  gcloud config set project <PROJECT_ID>
#   2) enabled billing + APIs (run, aiplatform, generativelanguage)
#   3) a MongoDB Atlas SRV connection string
# See DEPLOY_STEPS.md for the full ordered checklist.
#
# Usage:
#   PROJECT_ID=my-proj REGION=us-central1 \
#   MONGODB_URI='mongodb+srv://USER:PASS@cluster0.xxxx.mongodb.net/?retryWrites=true&w=majority' \
#   GEMINI_API_KEY='...'  ./deploy.sh
#
# Secrets are passed as env vars to this script and forwarded to the service via
# --set-env-vars. They are NOT written to any file in this repo.

set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
: "${MONGODB_URI:?set MONGODB_URI (Atlas SRV connection string)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-rulememory-cloud}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"

# Choose Gemini auth path: API key (simplest) or Vertex AI (uses the service account).
ENV_VARS="MONGODB_URI=${MONGODB_URI},GEMINI_MODEL=${GEMINI_MODEL}"
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  ENV_VARS="${ENV_VARS},GEMINI_API_KEY=${GEMINI_API_KEY}"
else
  ENV_VARS="${ENV_VARS},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION}"
fi
# Optional: point at a running MongoDB MCP server (HTTP transport).
if [[ -n "${MONGODB_MCP_URL:-}" ]]; then
  ENV_VARS="${ENV_VARS},MONGODB_MCP_URL=${MONGODB_MCP_URL}"
fi

echo ">> Deploying ${SERVICE} to project ${PROJECT_ID} in ${REGION} ..."
gcloud run deploy "${SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --source . \
  --allow-unauthenticated \
  --port 8080 \
  --memory "${MEMORY:-1Gi}" \
  --set-env-vars "${ENV_VARS}"

echo ">> Hosted URL:"
gcloud run services describe "${SERVICE}" \
  --project "${PROJECT_ID}" --region "${REGION}" \
  --format='value(status.url)'
