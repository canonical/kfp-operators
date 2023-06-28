## Kubeflow Pipelines Operators

### Overview
This bundle encompasses the Kubernetes Python operators for Kubeflow Pipelines (see
[CharmHub](https://charmhub.io/?q=kubeflow-pipelines)).

The Kubeflow Pipelines operators are Python scripts that wrap the latest released version
of Kubeflow Pipelines, providing lifecycle management and handling events such as installing,
upgrading, integration, and removal.

## Install

To install Kubeflow Pipelines, run:

    juju deploy kubeflow-pipelines

For more information, see https://juju.is/docs

## Development and testing

### Interacting with the MinIO blob store

To peek inside the MinIO store, use the MinIO client (`mc`):

```
kubectl run minioclient -i --tty --rm --image minio/mc -n kubeflow --command -- /bin/sh
mc alias set myalias http://minio.kubeflow:9000 ACCESSKEY SECRETKEY
mc ls myalias
```

You can then use other `mc` commands to interact with the contents of the store.

### Interacting with the KFP Database

When debugging KFP, it is sometime useful to interact directly with the database (to confirm that an experiment was written to the DB, etc).  To get a client on-cluster to do so, try:

```
kubectl run dbclient -i --tty --rm --image mariadb -n kubeflow -- /bin/bash
# (from inside session)
mysql -h KFPDB_SVC_IP -u mysql -D mlpipeline -p 
# (enter password, `password`)
```

This will start a mysql interactive shell inside the dbclient pod, you can then use queries like:
```sql
SHOW DATABASES;
USE databasename;
SHOW TABLES;
```

which yields: 
```
+----------------------+
| Tables_in_mlpipeline |
+----------------------+
| db_statuses          |
| default_experiments  |
| experiments          |
| jobs                 |
| pipeline_versions    |
| pipelines            |
| resource_references  |
| run_details          |
| run_metrics          |
| tasks                |
+----------------------+
```

or:
```sql
SELECT * FROM pipelines
```

Some useful queries for the KFP DB:

Query experiments
```sql
SELECT `experiments`.`UUID`,
    `experiments`.`Name`,
    `experiments`.`Description`,
    `experiments`.`CreatedAtInSec`,
    `experiments`.`Namespace`,
    `experiments`.`StorageState`
FROM `mlpipeline`.`experiments`;
```

Insert Experiments
```sql
INSERT INTO `mlpipeline`.`experiments`
(`UUID`,
`Name`,
`Description`,
`CreatedAtInSec`,
`Namespace`,
`StorageState`)
VALUES
('uuid',
'addedExp',
'addedExpDesc',
3,
'admin',
'STORAGESTATE_AVAILABLE');
```

Query jobs
```sql
SELECT `jobs`.`UUID`,
    `jobs`.`DisplayName`,
    `jobs`.`Name`,
    `jobs`.`Namespace`,
    `jobs`.`ServiceAccount`,
    `jobs`.`Description`,
    `jobs`.`MaxConcurrency`,
    `jobs`.`NoCatchup`,
    `jobs`.`CreatedAtInSec`,
    `jobs`.`UpdatedAtInSec`,
    `jobs`.`Enabled`,
    `jobs`.`CronScheduleStartTimeInSec`,
    `jobs`.`CronScheduleEndTimeInSec`,
    `jobs`.`Schedule`,
    `jobs`.`PeriodicScheduleStartTimeInSec`,
    `jobs`.`PeriodicScheduleEndTimeInSec`,
    `jobs`.`IntervalSecond`,
    `jobs`.`PipelineId`,
    `jobs`.`PipelineName`,
    `jobs`.`PipelineSpecManifest`,
    `jobs`.`WorkflowSpecManifest`,
    `jobs`.`Parameters`,
    `jobs`.`Conditions`
FROM `mlpipeline`.`jobs`;
```

Query pipelines
```sql
SELECT `pipelines`.`UUID`,
    `pipelines`.`CreatedAtInSec`,
    `pipelines`.`Name`,
    `pipelines`.`Description`,
    `pipelines`.`Parameters`,
    `pipelines`.`Status`,
    `pipelines`.`DefaultVersionId`,
    `pipelines`.`Namespace`
FROM `mlpipeline`.`pipelines`;
```

Insert pipelines
```sql
INSERT INTO `mlpipeline`.`pipelines`
(`UUID`,
`CreatedAtInSec`,
`Name`,
`Description`,
`Parameters`,
`Status`,
`DefaultVersionId`,
`Namespace`)
VALUES
(1,
1,
1,
1,
1,
1,
1,
1);
```
