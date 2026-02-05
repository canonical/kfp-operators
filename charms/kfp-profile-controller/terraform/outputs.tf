output "app_name" {
  value = juju_application.kfp_profile_controller.name
}

output "provides" {
  value = {
    provide_cmr_mesh = "provide-cmr-mesh"
  }
}

output "requires" {
  value = {
    logging          = "logging",
    object_storage   = "object-storage",
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
  }
}
