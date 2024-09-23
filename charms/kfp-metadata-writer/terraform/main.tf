resource "juju_application" "kfp_metadata_writer" {
  charm {
    name     = "kfp-metadata-writer"
    channel  = var.channel
    revision = var.revision
  }
  config    = var.config
  model     = var.model_name
  name      = var.app_name
  resources = var.resources
  trust     = true
  units     = 1
}
