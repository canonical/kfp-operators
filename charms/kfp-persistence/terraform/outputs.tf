output "app_name" {
  value = juju_application.kfp_api.name
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
