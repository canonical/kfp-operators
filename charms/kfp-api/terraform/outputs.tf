output "app_name" {
  value = juju_application.kfp_api.name
}

output "provides" {
  value = {
    kfp_api           = "kfp-api",
    metrics_endpoint  = "metrics-endpoint",
    grafana_dashboard = "grafana-dashboard",
  }
}

output "requires" {
  value = {
    mysql          = "mysql",
    relational_db  = "relational-db",
    object_storage = "object-storage",
    kfp_viz        = "kfp-viz",
    logging        = "logging",
  }
}
