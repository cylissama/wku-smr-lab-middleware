# On accessing the database

As stated the [PostgresSQL](https://www.postgresql.org) database is located on the Synology NAS. There is also an instance of [pgAdmin](https://www.pgadmin.org) running alongside the database on the NAS.

pgAdmin is used to view the database and make queries on the data. You can also download data from the database using pgAdmin.

There is link to the pgAdmin server on the Data Dashboard. You can also find the exact location of the pgAdmin server on the [ip-addresses](/network/ip-addresses.md) table located on the shared onedrive or on the documentation page here.

# Once logged into pgAdmin

Initially when you land on the pgAdmin webpage, you might only see the "Servers(1)" listing on the left hand navigation panel.

To view the schema drill down into:

Servers -> ManufactoringDB -> Databases -> manufactoring_db -> Schemas -> public -> Tables

This will diplay what tables are present and once drilled into, what attributes the tables have

For example the device table has columns of 
- id, label, category, ip_address, registered

This database uses typical SQL, so any SQL query can run here. Some usefull examples are:

To grab some camera edge node data based on session
```
SELECT *
FROM image_detection
WHERE session_id = <xxx>
```

To grab some imu edge node data based on session
```
SELECT *
FROM imu_measurements
WHERE session_id = <xxx>
```