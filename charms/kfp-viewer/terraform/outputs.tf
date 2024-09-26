output "app_name" {
  value = juju_application.kfp_viewer.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    logging = "logging"
  }
}
