output "app_name" {
  value = juju_application.kfp_viz.name
}

output "provides" {
  value = {
    kfp_viz          = "kfp-viz",
    provide_cmr_mesh = "provide-cmr-mesh"
  }
}

output "requires" {
  value = {
    logging          = "logging",
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
  }
}
