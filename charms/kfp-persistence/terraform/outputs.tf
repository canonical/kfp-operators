output "app_name" {
  value = juju_application.kfp_persistence.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    kfp_api = "kfp-api",
    logging = "logging"
  }
}
