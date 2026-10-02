# Bootstrap Azure and GitHub OIDC

This directory contains the one-time trust setup. It creates:

- an Azure Storage account and blob container for Terraform state;
- a read-only GitHub OIDC identity for pull-request plans; and
- an apply GitHub OIDC identity for the protected `staging` environment.

The bootstrap is intentionally separate from the application Terraform state.
Terraform cannot safely create the credentials it needs to authenticate its own
first run.

## Prerequisites

- Azure CLI installed and authenticated with `az login`;
- permission to create resource groups, storage accounts, app registrations,
  service principals, and role assignments;
- the GitHub repository name in `owner/name` form.

Run from the repository root:

```bash
az account set --subscription "<YOUR_SUBSCRIPTION_ID>"

export GITHUB_REPOSITORY=alazark777/booking-assist
export AZURE_SUBSCRIPTION_ID="<YOUR_SUBSCRIPTION_ID>"
export AZURE_TENANT_ID="<YOUR_TENANT_ID>"

bash infra/bootstrap/bootstrap.sh
```

The script is idempotent for the resource names it controls. It prints the
client IDs and Terraform backend values needed by the GitHub `staging`
environment. Store those as GitHub variables, not as repository files.

## Permissions

The plan identity receives `Reader` on the subscription and
`Storage Blob Data Contributor` on the state account. The apply identity
temporarily receives `Contributor`, `User Access Administrator`, and state
storage access at subscription/state scopes because the initial Terraform
apply creates the resource group and managed-identity role assignments.

After the first successful deployment, review the role assignments and reduce
the apply identity to the staging resource group plus the narrowly required
role-assignment scope. Never replace OIDC with a client secret committed to
GitHub.
