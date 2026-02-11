output "app_name" {
  value = juju_application.kfp_persistence.name
}

output "provides" {
  value = {
    provide_cmr_mesh = "provide-cmr-mesh"
  }
}

output "requires" {
  value = {
    kfp_api          = "kfp-api",
    kfp_api_grpc     = "kfp-api-grpc",
    logging          = "logging",
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
  }
}
