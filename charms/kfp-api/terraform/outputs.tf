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
<<<<<<< HEAD
    mysql          = "mysql",
    relational_db  = "relational-db",
    object_storage = "object-storage",
    kfp_viz        = "kfp-viz",
    logging        = "logging",
=======
    kfp_viz          = "kfp-viz",
    logging          = "logging",
    object_storage   = "object-storage",
    relational_db    = "relational-db",
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
>>>>>>> dd3b8d1 (feat: Remove deprecated 'mysql' endpoint (#975))
  }
}
