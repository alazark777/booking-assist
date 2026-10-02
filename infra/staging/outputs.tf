output "resource_group_name" {
  description = "Staging resource group."
  value       = azurerm_resource_group.staging.name
}

output "acr_name" {
  description = "Azure Container Registry name."
  value       = azurerm_container_registry.staging.name
}

output "acr_login_server" {
  description = "Azure Container Registry login server."
  value       = azurerm_container_registry.staging.login_server
}

output "container_app_name" {
  description = "API Container App name."
  value       = azurerm_container_app.api.name
}

output "container_app_url" {
  description = "Public HTTPS URL for the API."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "migration_job_name" {
  description = "Manual Container Apps migration job name."
  value       = azurerm_container_app_job.migration.name
}

output "postgres_server_name" {
  description = "PostgreSQL Flexible Server name."
  value       = azurerm_postgresql_flexible_server.database.name
}

output "key_vault_name" {
  description = "Key Vault storing runtime secrets."
  value       = azurerm_key_vault.staging.name
}
