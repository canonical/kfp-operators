output "app_name" {
  value = juju_application.kfp_viz.name
}

output "provides" {
  value = {
    kfp_viz = "kfp-viz"
  }
}

output "requires" {
  value = {
    logging = "logging"
  }
}
