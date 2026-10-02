data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  lower   = true
  numeric = true
  special = false
  upper   = false
}

resource "random_password" "postgres_admin" {
  count = var.postgres_admin_password == null ? 1 : 0

  length  = 32
  special = false
}

locals {
  base_name         = "${var.name_prefix}-${var.environment}-${random_string.suffix.result}"
  acr_name          = substr(replace("${var.name_prefix}${var.environment}${random_string.suffix.result}", "-", ""), 0, 50)
  key_vault_name    = substr(replace("${var.name_prefix}${var.environment}${random_string.suffix.result}kv", "-", ""), 0, 24)
  postgres_name     = substr(replace("${local.base_name}-pg", "_", "-"), 0, 63)
  postgres_password = var.postgres_admin_password != null ? var.postgres_admin_password : random_password.postgres_admin[0].result
  database_url = format(
    "postgresql+asyncpg://%s:%s@%s:5432/appointment_assistant?ssl=require",
    var.postgres_admin_username,
    urlencode(local.postgres_password),
    azurerm_postgresql_flexible_server.database.fqdn,
  )
}

resource "azurerm_resource_group" "staging" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    application = var.name_prefix
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_log_analytics_workspace" "staging" {
  name                = "${local.base_name}-logs"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_registry" "staging" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.staging.name
  location            = azurerm_resource_group.staging.location
  sku                 = "Basic"
  admin_enabled       = false

  tags = {
    application = var.name_prefix
    environment = var.environment
  }
}

resource "azurerm_virtual_network" "staging" {
  name                = "${local.base_name}-vnet"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
  address_space       = ["10.40.0.0/16"]
}

resource "azurerm_subnet" "container_apps" {
  name                 = "container-apps"
  resource_group_name  = azurerm_resource_group.staging.name
  virtual_network_name = azurerm_virtual_network.staging.name
  address_prefixes     = ["10.40.0.0/23"]

  delegation {
    name = "container-apps-delegation"

    service_delegation {
      name = "Microsoft.App/environments"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.staging.name
  virtual_network_name = azurerm_virtual_network.staging.name
  address_prefixes     = ["10.40.2.0/28"]

  delegation {
    name = "postgres-delegation"

    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.staging.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "${local.base_name}-postgres-dns"
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.staging.id
  resource_group_name   = azurerm_resource_group.staging.name
}

resource "azurerm_postgresql_flexible_server" "database" {
  name                          = local.postgres_name
  resource_group_name           = azurerm_resource_group.staging.name
  location                      = azurerm_resource_group.staging.location
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  administrator_login           = var.postgres_admin_username
  administrator_password        = local.postgres_password
  storage_mb                    = 32768
  sku_name                      = var.postgres_sku_name
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false

  depends_on = [
    azurerm_private_dns_zone_virtual_network_link.postgres,
  ]
}

resource "azurerm_postgresql_flexible_server_database" "application" {
  name      = "appointment_assistant"
  server_id = azurerm_postgresql_flexible_server.database.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_container_app_environment" "staging" {
  name                       = "${local.base_name}-env"
  location                   = azurerm_resource_group.staging.location
  resource_group_name        = azurerm_resource_group.staging.name
  infrastructure_subnet_id   = azurerm_subnet.container_apps.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.staging.id
  logs_destination           = "log-analytics"

  tags = {
    application = var.name_prefix
    environment = var.environment
  }
}

resource "azurerm_user_assigned_identity" "api" {
  name                = "${local.base_name}-api"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
}

resource "azurerm_user_assigned_identity" "migration" {
  name                = "${local.base_name}-migration"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
}

resource "azurerm_key_vault" "staging" {
  name                          = local.key_vault_name
  location                      = azurerm_resource_group.staging.location
  resource_group_name           = azurerm_resource_group.staging.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  public_network_access_enabled = true

  tags = {
    application = var.name_prefix
    environment = var.environment
  }
}

resource "azurerm_role_assignment" "terraform_key_vault_admin" {
  scope                = azurerm_key_vault.staging.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "api_acr_pull" {
  scope                = azurerm_container_registry.staging.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "migration_acr_pull" {
  scope                = azurerm_container_registry.staging.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.migration.principal_id
}

resource "azurerm_role_assignment" "terraform_acr_push" {
  scope                = azurerm_container_registry.staging.id
  role_definition_name = "AcrPush"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "api_key_vault_secrets_user" {
  scope                = azurerm_key_vault.staging.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "migration_key_vault_secrets_user" {
  scope                = azurerm_key_vault.staging.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.migration.principal_id
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = local.database_url
  key_vault_id = azurerm_key_vault.staging.id

  depends_on = [azurerm_role_assignment.terraform_key_vault_admin]
}

resource "azurerm_key_vault_secret" "google_api_key" {
  name         = "google-api-key"
  value        = var.google_api_key
  key_vault_id = azurerm_key_vault.staging.id

  depends_on = [azurerm_role_assignment.terraform_key_vault_admin]
}

resource "azurerm_key_vault_secret" "service_credentials" {
  name         = "service-credentials"
  value        = var.service_credentials
  key_vault_id = azurerm_key_vault.staging.id

  depends_on = [azurerm_role_assignment.terraform_key_vault_admin]
}

resource "azurerm_key_vault_secret" "langfuse_public_key" {
  name         = "langfuse-public-key"
  value        = var.langfuse_public_key == "" ? "disabled" : var.langfuse_public_key
  key_vault_id = azurerm_key_vault.staging.id

  depends_on = [azurerm_role_assignment.terraform_key_vault_admin]
}

resource "azurerm_key_vault_secret" "langfuse_secret_key" {
  name         = "langfuse-secret-key"
  value        = var.langfuse_secret_key == "" ? "disabled" : var.langfuse_secret_key
  key_vault_id = azurerm_key_vault.staging.id

  depends_on = [azurerm_role_assignment.terraform_key_vault_admin]
}

resource "azurerm_container_app" "api" {
  name                         = "${local.base_name}-api"
  container_app_environment_id = azurerm_container_app_environment.staging.id
  resource_group_name          = azurerm_resource_group.staging.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  registry {
    server   = azurerm_container_registry.staging.login_server
    identity = azurerm_user_assigned_identity.api.id
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.api.id
  }

  secret {
    name                = "google-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.google_api_key.versionless_id
    identity            = azurerm_user_assigned_identity.api.id
  }

  secret {
    name                = "service-credentials"
    key_vault_secret_id = azurerm_key_vault_secret.service_credentials.versionless_id
    identity            = azurerm_user_assigned_identity.api.id
  }

  secret {
    name                = "langfuse-public-key"
    key_vault_secret_id = azurerm_key_vault_secret.langfuse_public_key.versionless_id
    identity            = azurerm_user_assigned_identity.api.id
  }

  secret {
    name                = "langfuse-secret-key"
    key_vault_secret_id = azurerm_key_vault_secret.langfuse_secret_key.versionless_id
    identity            = azurerm_user_assigned_identity.api.id
  }

  ingress {
    external_enabled           = true
    target_port                = 8000
    transport                  = "auto"
    allow_insecure_connections = false

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "api"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      env {
        name        = "GOOGLE_API_KEY"
        secret_name = "google-api-key"
      }

      env {
        name        = "SERVICE_CREDENTIALS"
        secret_name = "service-credentials"
      }

      env {
        name  = "APP_ENV"
        value = var.environment
      }

      env {
        name  = "GOOGLE_MODEL"
        value = var.google_model
      }

      env {
        name  = "BOOKING_WRITES_ENABLED"
        value = tostring(var.booking_writes_enabled)
      }

      env {
        name  = "LANGFUSE_TRACING_ENABLED"
        value = tostring(var.langfuse_tracing_enabled)
      }

      env {
        name        = "LANGFUSE_PUBLIC_KEY"
        secret_name = "langfuse-public-key"
      }

      env {
        name        = "LANGFUSE_SECRET_KEY"
        secret_name = "langfuse-secret-key"
      }

      env {
        name  = "LANGFUSE_BASE_URL"
        value = var.langfuse_base_url
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health/live"
        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health/ready"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.api_acr_pull,
    azurerm_role_assignment.api_key_vault_secrets_user,
  ]
}

resource "azurerm_container_app_job" "migration" {
  name                         = "${local.base_name}-migration"
  location                     = azurerm_resource_group.staging.location
  resource_group_name          = azurerm_resource_group.staging.name
  container_app_environment_id = azurerm_container_app_environment.staging.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.migration.id]
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  registry {
    server   = azurerm_container_registry.staging.login_server
    identity = azurerm_user_assigned_identity.migration.id
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.migration.id
  }

  template {
    container {
      name    = "migration"
      image   = var.container_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["sh", "-c"]
      args    = ["uv run --no-sync alembic upgrade head && uv run --no-sync python -m appointment_assistant.seed"]

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.migration_acr_pull,
    azurerm_role_assignment.migration_key_vault_secrets_user,
  ]
}
