output "app_name" {
  value = juju_application.kfp_metadata_writer.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    grpc    = "grpc",
    logging = "logging"
  }
}
