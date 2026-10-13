#!/usr/bin/env bash
# Narrow the GitHub Actions apply identity after the first successful deploy.
# Removes subscription-wide Contributor / User Access Administrator and scopes
# those roles to the staging application resource group only.
#
# Values are read from the GitHub staging environment so a stale local
# bootstrap file cannot pin roles to a retired resource group.
set -euo pipefail

repository="${GITHUB_REPOSITORY:-alazark777/booking-assist}"

command -v az >/dev/null || {
  printf 'Missing required command: az\n' >&2
  exit 1
}
command -v gh >/dev/null || {
  printf 'Missing required command: gh\n' >&2
  exit 1
}

AZURE_SUBSCRIPTION_ID="$(gh variable get AZURE_SUBSCRIPTION_ID --repo "$repository" --env staging)"
AZURE_CLIENT_ID_APPLY="$(gh variable get AZURE_CLIENT_ID_APPLY --repo "$repository" --env staging)"
AZURE_RESOURCE_GROUP="$(gh variable get AZURE_RESOURCE_GROUP --repo "$repository" --env staging)"
TF_STATE_RESOURCE_GROUP="$(gh variable get TF_STATE_RESOURCE_GROUP --repo "$repository" --env staging)"
TF_STATE_STORAGE_ACCOUNT="$(gh variable get TF_STATE_STORAGE_ACCOUNT --repo "$repository" --env staging)"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

apply_principal_id="$(az ad sp show --id "$AZURE_CLIENT_ID_APPLY" --query id -o tsv)"
subscription_scope="/subscriptions/${AZURE_SUBSCRIPTION_ID}"
application_scope="${subscription_scope}/resourceGroups/${AZURE_RESOURCE_GROUP}"
state_scope="${subscription_scope}/resourceGroups/${TF_STATE_RESOURCE_GROUP}/providers/Microsoft.Storage/storageAccounts/${TF_STATE_STORAGE_ACCOUNT}"

if ! az group show --name "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  printf 'Application resource group %s was not found. Create it or keep subscription-wide bootstrap roles until the first deploy succeeds.\n' "$AZURE_RESOURCE_GROUP" >&2
  exit 1
fi

create_role() {
  local role="$1"
  local scope="$2"
  if az role assignment create \
    --assignee-object-id "$apply_principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "$role" \
    --scope "$scope" \
    >/dev/null; then
    printf 'Ensured %s on %s\n' "$role" "$scope"
  else
    printf 'Could not ensure %s on %s. If the subscription is disabled/read-only, re-run this script after re-enabling it.\n' "$role" "$scope" >&2
  fi
}

delete_role() {
  local role="$1"
  local scope="$2"
  if az role assignment delete \
    --assignee-object-id "$apply_principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "$role" \
    --scope "$scope" \
    >/dev/null 2>&1; then
    printf 'Removed %s from %s\n' "$role" "$scope"
  else
    printf 'No %s assignment found on %s\n' "$role" "$scope"
  fi
}

# Prefer scoped roles first so a later failure still leaves a least-privilege path
# when the subscription is writable.
create_role "Contributor" "$application_scope"
create_role "User Access Administrator" "$application_scope"
create_role "Storage Blob Data Contributor" "$state_scope"

# Remove the temporary subscription-wide bootstrap roles.
delete_role "Contributor" "$subscription_scope"
delete_role "User Access Administrator" "$subscription_scope"

printf '\nHardened apply identity %s\n' "$AZURE_CLIENT_ID_APPLY"
printf 'Current assignments:\n'
az role assignment list \
  --assignee-object-id "$apply_principal_id" \
  --all \
  --query '[].{role:roleDefinitionName,scope:scope}' \
  -o table
