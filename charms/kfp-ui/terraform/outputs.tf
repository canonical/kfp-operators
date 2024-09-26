output "app_name" {
  value = juju_application.kfp_ui.name
}

output "provides" {
  value = {
    kfp_ui = "kfp-ui"
  }
}

output "requires" {
  value = {
    object_storage  = "object-storage",
    kfp_api         = "kfp-api",
    ingress         = "ingress",
    dashboard_links = "dashboard-links",
    logging         = "logging"
  }
}
