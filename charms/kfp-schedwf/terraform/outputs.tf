output "app_name" {
  value = juju_application.kfp_schedwf.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    logging = "logging"
  }
}
