#!/usr/bin/env bash
set -euo pipefail

required_commands=(az gh)
for command_name in "${required_commands[@]}"; do
  command -v "$command_name" >/dev/null || {
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  }
done

: "${GITHUB_REPOSITORY:?Set GITHUB_REPOSITORY, for example alazark777/booking-assist}"
: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID}"
: "${AZURE_TENANT_ID:?Set AZURE_TENANT_ID}"
: "${STATE_RESOURCE_GROUP:=booking-assist-tfstate}"
: "${STATE_LOCATION:=eastus}"
: "${STATE_CONTAINER:=tfstate}"
: "${APPLICATION_RESOURCE_GROUP:=booking-assist-staging}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

for provider_namespace in \
  Microsoft.App \
  Microsoft.ContainerRegistry \
  Microsoft.DBforPostgreSQL \
  Microsoft.KeyVault \
  Microsoft.Network \
  Microsoft.OperationalInsights \
  Microsoft.Storage; do
  az provider register --namespace "$provider_namespace" --wait >/dev/null
done

repository_owner="$(gh api "repos/${GITHUB_REPOSITORY}" --jq '.owner.login')"
repository_owner_id="$(gh api "repos/${GITHUB_REPOSITORY}" --jq '.owner.id')"
repository_name="$(gh api "repos/${GITHUB_REPOSITORY}" --jq '.name')"
repository_id="$(gh api "repos/${GITHUB_REPOSITORY}" --jq '.id')"
oidc_subject_prefix="repo:${repository_owner}@${repository_owner_id}/${repository_name}@${repository_id}"

state_storage_account="${STATE_STORAGE_ACCOUNT:-bookingassiststate$(printf '%s' "$AZURE_SUBSCRIPTION_ID" | tr -d '-' | cut -c1-6)}"
for value in "$state_storage_account" "$STATE_RESOURCE_GROUP" "$STATE_CONTAINER"; do
  if [[ "$value" =~ [A-Z] || "$value" =~ [^a-zA-Z0-9-] ]]; then
    printf 'Invalid Azure resource name: %s\n' "$value" >&2
    exit 1
  fi
done
if [[ ! "$state_storage_account" =~ ^[a-z0-9]{3,24}$ ]]; then
  printf 'STATE_STORAGE_ACCOUNT must be 3-24 lowercase letters or numbers: %s\n' "$state_storage_account" >&2
  exit 1
fi

az group create \
  --name "$STATE_RESOURCE_GROUP" \
  --location "$STATE_LOCATION" \
  --tags application=booking-assist purpose=terraform-state managed_by=bootstrap

az storage account create \
  --name "$state_storage_account" \
  --resource-group "$STATE_RESOURCE_GROUP" \
  --location "$STATE_LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --https-only true \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --default-action Allow \
  --bypass AzureServices

az storage account blob-service-properties update \
  --account-name "$state_storage_account" \
  --resource-group "$STATE_RESOURCE_GROUP" \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days 7

az storage container create \
  --name "$STATE_CONTAINER" \
  --account-name "$state_storage_account" \
  --auth-mode login

create_oidc_identity() {
  local name="$1"
  local subject="$2"
  local app_id
  local credential_name
  local service_principal_id
  local subject_hash

  app_id="$(az ad app list --display-name "$name" --query '[0].appId' -o tsv)"
  if [[ -z "$app_id" ]]; then
    app_id="$(az ad app create --display-name "$name" --query appId -o tsv)"
  fi

  if ! az ad sp show --id "$app_id" >/dev/null 2>&1; then
    az ad sp create --id "$app_id" >/dev/null
  fi

  service_principal_id="$(az ad sp show --id "$app_id" --query id -o tsv)"
  if command -v sha256sum >/dev/null; then
    subject_hash="$(printf '%s' "$subject" | sha256sum | cut -c1-8)"
  else
    subject_hash="$(printf '%s' "$subject" | shasum -a 256 | cut -c1-8)"
  fi
  credential_name="github-${name// /-}-${subject_hash}"
  az ad app federated-credential create \
    --id "$app_id" \
    --parameters "{\"name\":\"${credential_name}\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"${subject}\",\"audiences\":[\"api://AzureADTokenExchange\"]}" \
    >/dev/null 2>&1 || true

  printf '%s\t%s\t%s\n' "$name" "$app_id" "$service_principal_id"
}

plan_identity="$(create_oidc_identity "booking-assist-staging-plan" "${oidc_subject_prefix}:pull_request")"
apply_identity="$(create_oidc_identity "booking-assist-staging-apply" "${oidc_subject_prefix}:environment:staging")"

plan_client_id="$(printf '%s' "$plan_identity" | cut -f2)"
plan_principal_id="$(printf '%s' "$plan_identity" | cut -f3)"
apply_client_id="$(printf '%s' "$apply_identity" | cut -f2)"
apply_principal_id="$(printf '%s' "$apply_identity" | cut -f3)"

subscription_scope="/subscriptions/${AZURE_SUBSCRIPTION_ID}"
state_scope="${subscription_scope}/resourceGroups/${STATE_RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${state_storage_account}"

az role assignment create \
  --assignee-object-id "$plan_principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role Reader \
  --scope "$subscription_scope" \
  >/dev/null 2>&1 || true
az role assignment create \
  --assignee-object-id "$plan_principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "$state_scope" \
  >/dev/null 2>&1 || true

# The apply identity needs to create the staging resource group and role
# assignments for managed identities. Narrow these assignments after the first
# successful apply if your organization pre-creates the resource group and has
# a dedicated RBAC administrator.
az role assignment create \
  --assignee-object-id "$apply_principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role Contributor \
  --scope "$subscription_scope" \
  >/dev/null 2>&1 || true
az role assignment create \
  --assignee-object-id "$apply_principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "User Access Administrator" \
  --scope "$subscription_scope" \
  >/dev/null 2>&1 || true
az role assignment create \
  --assignee-object-id "$apply_principal_id" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "$state_scope" \
  >/dev/null 2>&1 || true

bootstrap_output_file="${BOOTSTRAP_OUTPUT_FILE:-.staging-bootstrap.env}"
umask 077
cat > "$bootstrap_output_file" <<EOF
AZURE_CLIENT_ID_APPLY=$apply_client_id
AZURE_CLIENT_ID_PLAN=$plan_client_id
AZURE_SUBSCRIPTION_ID=$AZURE_SUBSCRIPTION_ID
AZURE_TENANT_ID=$AZURE_TENANT_ID
TF_STATE_RESOURCE_GROUP=$STATE_RESOURCE_GROUP
TF_STATE_STORAGE_ACCOUNT=$state_storage_account
TF_STATE_CONTAINER=$STATE_CONTAINER
AZURE_RESOURCE_GROUP=$APPLICATION_RESOURCE_GROUP
EOF

cat <<EOF
Bootstrap complete.

Machine-readable values were written to: $bootstrap_output_file

Configure these GitHub repository/environment variables:
  AZURE_CLIENT_ID_PLAN=$plan_client_id
  AZURE_CLIENT_ID_APPLY=$apply_client_id
  AZURE_SUBSCRIPTION_ID=$AZURE_SUBSCRIPTION_ID
  AZURE_TENANT_ID=$AZURE_TENANT_ID
  TF_STATE_RESOURCE_GROUP=$STATE_RESOURCE_GROUP
  TF_STATE_STORAGE_ACCOUNT=$state_storage_account
  TF_STATE_CONTAINER=$STATE_CONTAINER
  AZURE_RESOURCE_GROUP=$APPLICATION_RESOURCE_GROUP

The apply identity is intentionally broad during bootstrap because Terraform
creates the application resource group and managed-identity role assignments.
Review and reduce its scope after the first successful deployment.
EOF
