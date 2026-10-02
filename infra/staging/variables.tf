variable "subscription_id" {
  description = "Azure subscription that owns the staging resources."
  type        = string
}

variable "location" {
  description = "Azure region for the staging resources."
  type        = string
  default     = "westus3"
}

variable "resource_group_name" {
  description = "Resource group containing the staging application."
  type        = string
  default     = "booking-assist-staging-westus3"
}

variable "name_prefix" {
  description = "Short lowercase prefix used for globally unique Azure names."
  type        = string
  default     = "booking-assist"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.name_prefix))
    error_message = "name_prefix must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "staging"
}

variable "container_image" {
  description = "Fully qualified image reference. The placeholder is used only for first-time infrastructure creation."
  type        = string
  default     = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
}

variable "google_api_key" {
  description = "Google Gemini API key. Supply through TF_VAR_google_api_key or the GitHub environment."
  type        = string
  sensitive   = true
}

variable "service_credentials" {
  description = "Comma-separated bearer-token=principal pairs for staging."
  type        = string
  sensitive   = true
  default     = "alice-token=customer-a,bob-token=customer-b"
}

variable "booking_writes_enabled" {
  description = "Whether staging may create synthetic bookings."
  type        = bool
  default     = false
}

variable "google_model" {
  description = "Gemini model used by the API."
  type        = string
  default     = "gemini-3.8-flash"
}

variable "postgres_admin_username" {
  description = "Administrator login for PostgreSQL Flexible Server."
  type        = string
  default     = "appointmentadmin"
}

variable "postgres_admin_password" {
  description = "Optional PostgreSQL administrator password. If omitted, Terraform generates one and stores it in protected state."
  type        = string
  sensitive   = true
  default     = null
}

variable "postgres_sku_name" {
  description = "PostgreSQL Flexible Server SKU for staging."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "langfuse_tracing_enabled" {
  description = "Enable optional Langfuse tracing in staging."
  type        = bool
  default     = false
}

variable "langfuse_public_key" {
  description = "Optional Langfuse public key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "langfuse_secret_key" {
  description = "Optional Langfuse secret key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "langfuse_base_url" {
  description = "Langfuse base URL."
  type        = string
  default     = "https://cloud.langfuse.com"
}
