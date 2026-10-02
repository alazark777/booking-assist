# Automated Azure staging deployment

This repository uses Terraform for Azure infrastructure and GitHub Actions for
the application delivery pipeline.

## What is automated

```text
Pull request
  -> application tests and Terraform plan

Push to main
  -> GitHub OIDC login to Azure
  -> build image tagged with the commit SHA
  -> push image to Azure Container Registry
  -> Terraform apply
  -> run the migration/seed job
  -> verify live and ready endpoints
```

The API runs on Azure Container Apps. PostgreSQL Flexible Server is private to
the virtual network. Secrets are stored in Key Vault and referenced by the
Container App through managed identities.

## One-time setup

The first setup needs an Azure operator because the deployment pipeline cannot
create the identity it uses to authenticate itself.

### 1. Log in and choose the subscription

```bash
az login
az account list -o table
az account set --subscription "<YOUR_SUBSCRIPTION_ID>"
```

### 2. Create Terraform state and GitHub OIDC identities

From the repository root:

```bash
export GITHUB_REPOSITORY=alazark777/booking-assist
export AZURE_SUBSCRIPTION_ID="<YOUR_SUBSCRIPTION_ID>"
export AZURE_TENANT_ID="<YOUR_TENANT_ID>"
bash infra/bootstrap/bootstrap.sh
bash scripts/configure-github-staging.sh .staging-bootstrap.env .env
```

The first script writes machine-readable values to
`.staging-bootstrap.env`. The second script creates/updates the GitHub
`staging` environment in one command, sets all variables, and reads the local
Google key without printing it. If the local key is unavailable, it writes a
placeholder that must be replaced before deployment.

You can also configure the environment manually at:

`Settings -> Environments -> staging -> Environment variables`

```text
AZURE_CLIENT_ID_APPLY
AZURE_CLIENT_ID_PLAN
AZURE_SUBSCRIPTION_ID
AZURE_TENANT_ID
TF_STATE_RESOURCE_GROUP
TF_STATE_STORAGE_ACCOUNT
TF_STATE_CONTAINER
AZURE_RESOURCE_GROUP
```

Create these as GitHub Actions secrets in the same `staging` environment:

```text
GOOGLE_API_KEY
SERVICE_CREDENTIALS
```

Do not commit `.env`, `terraform.tfvars`, Terraform state, API keys, database
passwords, or OIDC credentials. Terraform state is sensitive even when
resources use Key Vault references because secret resource values may be stored
in state. The bootstrap enables HTTPS, private blobs, versioning, and retention
for the state account.

### 3. Review Azure permissions

The bootstrap gives the apply identity broad permissions for the first apply:
`Contributor`, `User Access Administrator`, and state storage access. Terraform
needs this because it creates managed identities and their role assignments.
After the first successful deployment, review the assignments and reduce them
to the staging resource group and the exact role-assignment scopes approved by
your organization.

## First deployment

The first `main` deployment has two infrastructure passes:

1. Terraform creates the resource group, network, registry, database, Key Vault,
   Container Apps environment, and a temporary public hello-world image.
2. The workflow pushes the application image and applies Terraform again with
   the immutable application image.

This avoids the circular dependency where the Container App needs an image from
an ACR that Terraform has not created yet. Later deployments build the image
first and update the existing stack directly.

After the environment variables and secrets exist, deployment is automatic:
every push to `main` starts `deploy-staging`.

You can also start the same deployment manually from a terminal:

```bash
gh workflow run deploy-staging.yml \
  --repo alazark777/booking-assist \
  --ref main
```

Watch the run:

```bash
gh run watch --repo alazark777/booking-assist
```

List recent runs:

```bash
gh run list --repo alazark777/booking-assist --limit 5
```

The workflow will fail at Azure login if the OIDC client IDs are still
placeholders, or at the application step if `GOOGLE_API_KEY` is still a
placeholder. After correcting a value, rerun the workflow manually; no code
change is required.

## Local Terraform workflow

The GitHub workflow is the normal path, but these commands show what it does:

```bash
cd infra/staging

terraform init \
  -backend-config="resource_group_name=$TF_STATE_RESOURCE_GROUP" \
  -backend-config="storage_account_name=$TF_STATE_STORAGE_ACCOUNT" \
  -backend-config="container_name=$TF_STATE_CONTAINER" \
  -backend-config="key=booking-assist/staging.tfstate" \
  -backend-config="use_azuread_auth=true"

export TF_VAR_subscription_id="<YOUR_SUBSCRIPTION_ID>"
export TF_VAR_google_api_key="<SET_IN_YOUR_SHELL_ONLY>"

terraform plan \
  -var-file=terraform.tfvars.example \
  -var="subscription_id=$TF_VAR_subscription_id"
```

Do not put a real key in `terraform.tfvars.example`. For local testing, use a
temporary shell environment or a private untracked `.tfvars` file.

## Inspecting the deployment

```bash
az containerapp list \
  --resource-group booking-assist-staging \
  -o table

terraform -chdir=infra/staging output

bash scripts/verify-staging.sh "$(terraform -chdir=infra/staging output -raw container_app_url)"
```

View API logs:

```bash
az containerapp logs show \
  --name "<CONTAINER_APP_NAME>" \
  --resource-group booking-assist-staging \
  --follow
```

The migration job runs `alembic upgrade head` and then the repeatable synthetic
slot seed. It is deliberately separate from API startup so multiple API
replicas cannot race migrations.

## Rollback

Every image is tagged with its Git commit SHA. To roll back:

1. Identify the previous successful SHA in GitHub Actions.
2. Re-run the deployment workflow with that SHA or update the
   `container_image` Terraform variable to the previous ACR image.
3. Run the migration job only if the rollback includes a compatible migration.
4. Confirm `/health/live` and `/health/ready`.

Database migrations must remain backward-compatible with the previous image
until rollback is no longer needed.

## Teardown

Review the impact before destroying staging. This removes the application,
database, Key Vault, registry, network, and logging resources:

```bash
terraform -chdir=infra/staging destroy
```

Terraform state storage and the GitHub OIDC identities are intentionally
outside the application state. Remove them separately only when the repository
will no longer be deployed.

## Important limitations

- `SERVICE_CREDENTIALS` is a synthetic bearer-token map intended for staging.
  It is not an organization identity provider.
- `MockScheduler` is still a demo scheduler; it does not book a real calendar.
- `BOOKING_WRITES_ENABLED` defaults to `false` in staging.
- Langfuse content capture remains disabled by default.
- PostgreSQL and Terraform state are billable Azure resources. Review the
  selected SKU, retention, and budget alerts before using this beyond staging.
