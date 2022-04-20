# Manual Testing

To manually test this charm, you can:

* deploy kfp-db charm with `juju deploy charmed-osm-mariadb-k8s kfp-db` & configure with `juju config kfp-db database=mlpipeline`
* deploy kfp-api charm & relate to kfp-db
* deploy minio & relate to kfp-api
* deploy kfp-viz & relate to kfp-api

To test grafana and prometheus integration:
* deploy prometheus-k8s & relate to kfp-api
* deploy grafana-k8s & relate to kfp-api and prometheus-k8s 
* get the default grafana password with `juju run-action grafana-k8s/0 get-admin-password --wait`
* get grafana and prometheus pods IPs using `juju status` or `kubectl get pods`
* test grafana connection: http://GRAFANA_IP_ADDRESS:3000
* test prometheus connection: http://PROMETHEUS_IP_ADDRESS:9090

To set the prometheus scrape interval:
* deploy the scrape-config charm with `juju deploy prometheus-scrape-config-k8s scrape-interval-config --config scrape_interval=20s --channel beta`
* relate it to kfp-api and prometheus-k8s
