output "app_name" {
  value = juju_application.kfp_api.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    object_storage = "object-storage",
    logging        = "logging",
  }
}
