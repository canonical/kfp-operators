output "app_name" {
  value = juju_application.kfp_ui.name
}

output "provides" {
  value = {
    kfp_ui           = "kfp-ui",
    provide_cmr_mesh = "provide-cmr-mesh"
  }
}

output "requires" {
  value = {
    dashboard_links     = "dashboard-links",
    ingress             = "ingress",
    istio_ingress_route = "istio-ingress-route",
    kfp_api             = "kfp-api",
    logging             = "logging",
    object_storage      = "object-storage",
    require_cmr_mesh    = "require-cmr-mesh",
    service_mesh        = "service-mesh"
  }
}
