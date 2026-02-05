output "app_name" {
  value = juju_application.kfp_api.name
}

output "provides" {
  value = {
    grafana_dashboard = "grafana-dashboard",
    kfp_api           = "kfp-api",
    kfp_api_grpc      = "kfp-api-grpc",
    metrics_endpoint  = "metrics-endpoint",
    provide_cmr_mesh  = "provide-cmr-mesh"
  }
}

output "requires" {
  value = {
    kfp_viz          = "kfp-viz",
    logging          = "logging",
    mysql            = "mysql",
    object_storage   = "object-storage",
    relational_db    = "relational-db",
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
  }
}
